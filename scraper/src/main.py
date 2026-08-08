"""Orquestación del pipeline de scraping.

`run_pipeline()` contiene toda la lógica de negocio y es independiente del
Apify SDK, por lo que se puede probar directamente (dry_run, tests). `main()`
es el adaptador que lee el input mediante `Actor.get_input()`, ejecuta el
pipeline y publica los resultados con `Actor.push_data()`, funcionando tanto
en local (con almacenamiento emulado) como desplegado en Apify.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from .models import SearchResult
from .normalizers import (
    normalize_email,
    normalize_images,
    normalize_location,
    normalize_name,
    normalize_phone,
    normalize_rating,
    normalize_review_count,
    normalize_social_links,
    normalize_url,
)
from .profile_scraper import ProfileScraper
from .scoring import calculate_data_quality_score, calculate_score
from .search_provider import get_search_provider
from .storage import save_csv, save_json
from .utils import (
    filter_relevant_urls,
    log_final,
    log_score,
    log_search,
    logger,
    normalize_url_for_dedup,
)

DEFAULT_INPUT: Dict[str, Any] = {
    "keyword": "servicios de limpieza",
    "location": "Medellín, Colombia",
    "maxSearchResults": 20,
    "maxProfiles": 20,
    "minRating": 0,
    "minReviews": 0,
    "onlyVerified": False,
    "dryRun": False,
    "concurrency": 5,
    "requestTimeoutSecs": 30,
    "maxRetries": 2,
    "maxProfilesPerSite": 10,
}


def apply_dry_run_limits(actor_input: Dict[str, Any]) -> Dict[str, Any]:
    """En dry_run se limita todo a 3 resultados/perfiles como máximo."""
    actor_input = dict(actor_input)
    if actor_input.get("dryRun"):
        actor_input["maxSearchResults"] = min(int(actor_input.get("maxSearchResults") or 3), 3)
        actor_input["maxProfiles"] = min(int(actor_input.get("maxProfiles") or 3), 3)
        actor_input["concurrency"] = min(int(actor_input.get("concurrency") or 2), 2)
    return actor_input


def load_seed_results_from_file(path: str) -> List[SearchResult]:
    """Carga resultados de búsqueda "semilla" desde un JSON local.

    Formato esperado: lista de objetos {position, title, url, description}.
    Útil para pruebas locales/dry_run sin depender de una API externa.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [
        SearchResult(
            position=item.get("position", i + 1),
            title=item.get("title"),
            url=item["url"],
            description=item.get("description"),
        )
        for i, item in enumerate(raw)
    ]


def _clean_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


def _build_ok_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    profile_url = normalize_url(raw.get("profile_url")) or raw["profile_url"]
    images = normalize_images(raw.get("images") or [], base_url=raw["profile_url"])
    main_image = normalize_url(raw.get("main_image"), base_url=raw["profile_url"]) if raw.get("main_image") else None
    if main_image and main_image not in images:
        images.insert(0, main_image)
    if not main_image and images:
        main_image = images[0]

    rating = normalize_rating(raw.get("rating"))
    review_count = normalize_review_count(raw.get("review_count"))
    verified = bool(raw.get("verified"))
    google_position = raw.get("google_position")

    record = {
        "profile_url": profile_url,
        "domain": raw.get("domain"),
        "status": "ok",
        "error_type": None,
        "error": None,
        "name": normalize_name(raw.get("name")),
        "description": _clean_text(raw.get("description")),
        "location": normalize_location(raw.get("location")),
        "rating": rating,
        "review_count": review_count,
        "verified": verified,
        "main_image": main_image,
        "images": images,
        "public_phone": normalize_phone(raw.get("public_phone")),
        "public_whatsapp": normalize_url(raw.get("public_whatsapp")) if raw.get("public_whatsapp") else None,
        "public_email": normalize_email(raw.get("public_email")),
        "public_social": normalize_social_links(raw.get("public_social")),
        "google_position": google_position,
        "search_title": raw.get("search_title"),
        "search_description": raw.get("search_description"),
        "source_url": raw.get("source_url"),
        "scraped_at": raw.get("scraped_at"),
    }

    record["score"] = calculate_score(rating, review_count, verified, google_position)
    record["data_quality_score"] = calculate_data_quality_score(record)
    return record


def _build_error_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "profile_url": raw.get("profile_url"),
        "domain": raw.get("domain"),
        "status": raw.get("status", "error"),
        "error_type": raw.get("error_type"),
        "error": raw.get("error"),
        "name": None,
        "description": None,
        "location": None,
        "rating": None,
        "review_count": None,
        "verified": False,
        "main_image": None,
        "images": [],
        "public_phone": None,
        "public_whatsapp": None,
        "public_email": None,
        "public_social": None,
        "google_position": raw.get("google_position"),
        "search_title": raw.get("search_title"),
        "search_description": raw.get("search_description"),
        "source_url": raw.get("source_url"),
        "scraped_at": raw.get("scraped_at"),
        "score": None,
        "data_quality_score": None,
    }


def _passes_filters(record: Dict[str, Any], min_rating: float, min_reviews: int, only_verified: bool) -> bool:
    rating = record.get("rating") or 0
    reviews = record.get("review_count") or 0
    if rating < min_rating:
        return False
    if reviews < min_reviews:
        return False
    if only_verified and not record.get("verified"):
        return False
    return True


async def run_pipeline(
    actor_input: Dict[str, Any],
    seed_results: Optional[List[SearchResult]] = None,
) -> List[Dict[str, Any]]:
    """Ejecuta el pipeline completo y devuelve la lista final de registros."""
    merged = {**DEFAULT_INPUT, **actor_input}
    merged = apply_dry_run_limits(merged)

    keyword = merged["keyword"]
    location = merged["location"]
    max_search_results = int(merged["maxSearchResults"])
    max_profiles = int(merged["maxProfiles"])
    min_rating = float(merged.get("minRating") or 0)
    min_reviews = int(merged.get("minReviews") or 0)
    only_verified = bool(merged.get("onlyVerified"))

    if not keyword or not location:
        raise ValueError("Los campos 'keyword' y 'location' son obligatorios.")

    provider = get_search_provider(seed_results=seed_results)
    search_results = provider.search(keyword, location, max_search_results)
    log_search(keyword, location, len(search_results))

    url_to_search_result: Dict[str, SearchResult] = {}
    for sr in search_results:
        key = normalize_url_for_dedup(sr.url)
        if key not in url_to_search_result:
            url_to_search_result[key] = sr

    all_urls = [sr.url for sr in search_results]
    relevant_urls = filter_relevant_urls(all_urls)
    profile_urls = relevant_urls[:max_profiles]

    seed_urls: List[Dict[str, Any]] = []
    for url in profile_urls:
        sr = url_to_search_result.get(normalize_url_for_dedup(url))
        seed_urls.append(
            {
                "url": url,
                "google_position": sr.position if sr else None,
                "search_title": sr.title if sr else None,
                "search_description": sr.description if sr else None,
            }
        )

    scraper = ProfileScraper(
        concurrency=int(merged.get("concurrency") or 5),
        request_timeout_secs=int(merged.get("requestTimeoutSecs") or 30),
        max_retries=int(merged.get("maxRetries") or 2),
        respect_robots=True,
        max_profiles_per_site=int(merged.get("maxProfilesPerSite") or 0),
    )
    raw_results = await scraper.scrape(seed_urls)

    ranked_candidates: List[Dict[str, Any]] = []
    other_records: List[Dict[str, Any]] = []
    successful = 0

    for raw in raw_results:
        if raw.get("status") == "ok":
            successful += 1
            record = _build_ok_record(raw)
            if _passes_filters(record, min_rating, min_reviews, only_verified):
                ranked_candidates.append(record)
            else:
                record["status"] = "filtered"
                other_records.append(record)
        else:
            other_records.append(_build_error_record(raw))

    ranked_candidates.sort(
        key=lambda r: (-(r["score"] or 0), -(r["rating"] or 0), -(r["review_count"] or 0))
    )
    for i, record in enumerate(ranked_candidates, start=1):
        record["ranking"] = i
        log_score(record.get("name"), record["score"])

    for record in other_records:
        record["ranking"] = None

    final_records = ranked_candidates + other_records

    log_final(
        processed=len(raw_results),
        successful=successful,
        failed=len(raw_results) - successful,
        dataset_records=len(final_records),
    )

    return final_records


def _running_locally_without_apify_cli() -> bool:
    return not os.environ.get("APIFY_IS_AT_HOME")


async def main() -> None:
    from apify import Actor

    async with Actor:
        actor_input = await Actor.get_input() or {}
        merged_input = {**DEFAULT_INPUT, **actor_input}

        seed_results: Optional[List[SearchResult]] = None
        seed_file = os.environ.get("SEARCH_SEED_RESULTS_FILE")
        if seed_file and os.path.exists(seed_file):
            seed_results = load_seed_results_from_file(seed_file)
            logger.info("[SEARCH] Usando resultados semilla locales desde %s", seed_file)

        records = await run_pipeline(merged_input, seed_results=seed_results)

        for record in records:
            await Actor.push_data(record)

        if _running_locally_without_apify_cli():
            output_dir = os.environ.get("SCRAPER_OUTPUT_DIR", "data")
            save_json(records, os.path.join(output_dir, "dataset.json"))
            save_csv(records, os.path.join(output_dir, "dataset.csv"))
            logger.info("[FINAL] Dataset local guardado en %s/dataset.json y %s/dataset.csv", output_dir, output_dir)


if __name__ == "__main__":
    asyncio.run(main())
