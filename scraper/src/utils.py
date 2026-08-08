"""Utilidades compartidas: filtrado de URLs, deduplicación, logging y robots.txt."""
from __future__ import annotations

import logging
import re
import sys
import urllib.robotparser
from typing import Iterable, List, Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

logger = logging.getLogger("scraper")

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------
# Filtrado de dominios / URLs no relevantes
# --------------------------------------------------------------------------

BLOCKED_DOMAINS = {
    "google.com",
    "google.co",
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "fb.com",
    "instagram.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "pinterest.com",
}

BLOCKED_PATH_PATTERNS = [
    r"/login",
    r"/signin",
    r"/sign-in",
    r"/log-in",
    r"/register",
    r"/signup",
    r"/sign-up",
    r"/search",
    r"/s\?",
    r"/cgi-bin",
]

# Parámetros de tracking que es seguro eliminar de una URL sin romper la página.
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "igshid",
}


def get_domain(url: str) -> Optional[str]:
    """Devuelve el dominio (netloc sin www.) de una URL, o None si es inválida."""
    try:
        netloc = urlparse(url).netloc.lower()
    except Exception:
        return None
    if not netloc:
        return None
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or None


def is_blocked_domain(url: str) -> bool:
    domain = get_domain(url)
    if not domain:
        return True
    return any(domain == d or domain.endswith("." + d) for d in BLOCKED_DOMAINS)


def is_blocked_path(url: str) -> bool:
    path_and_query = urlparse(url).path.lower() + "?" + urlparse(url).query.lower()
    return any(re.search(pattern, path_and_query) for pattern in BLOCKED_PATH_PATTERNS)


def looks_like_directory_or_profile(url: str) -> bool:
    """Heurística simple para descartar URLs que claramente no son perfiles/directorios."""
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        return False
    if not parsed.netloc:
        return False
    # Descarta archivos estáticos (pdf, imágenes, etc.) que no son páginas de perfil.
    if re.search(r"\.(pdf|jpg|jpeg|png|gif|svg|zip|docx?|xlsx?)$", parsed.path.lower()):
        return False
    return True


def is_relevant_url(url: str) -> bool:
    """True si la URL es candidata a visitar como perfil/directorio público."""
    if not url:
        return False
    if is_blocked_domain(url):
        return False
    if is_blocked_path(url):
        return False
    if not looks_like_directory_or_profile(url):
        return False
    return True


def normalize_url_for_dedup(url: str) -> str:
    """Normaliza una URL para poder compararla y eliminar duplicados.

    No se usa para modificar la URL con la que se navega (solo para dedup),
    para no arriesgarse a romper la página real.
    """
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url.strip().lower()

    scheme = "https"
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/") or "/"

    query_pairs = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    query_pairs.sort()
    query = urlencode(query_pairs)

    return urlunparse((scheme, netloc, path, "", query, ""))


def dedupe_urls(urls: Iterable[str]) -> List[str]:
    """Elimina URLs duplicadas preservando el orden original."""
    seen = set()
    result = []
    for url in urls:
        if not url:
            continue
        key = normalize_url_for_dedup(url)
        if key in seen:
            continue
        seen.add(key)
        result.append(url)
    return result


def filter_relevant_urls(urls: Iterable[str]) -> List[str]:
    """Filtra y deduplica una lista de URLs, dejando solo candidatos relevantes."""
    deduped = dedupe_urls(urls)
    return [u for u in deduped if is_relevant_url(u)]


# --------------------------------------------------------------------------
# robots.txt
# --------------------------------------------------------------------------

_robots_cache: dict = {}


def is_allowed_by_robots(url: str, user_agent: str = "*") -> bool:
    """Comprueba robots.txt del dominio. Si no se puede obtener, asume permitido."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if base not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        try:
            rp.read()
        except Exception:
            _robots_cache[base] = None  # no se pudo leer -> no bloquear
        else:
            _robots_cache[base] = rp
    rp = _robots_cache[base]
    if rp is None:
        return True
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


# --------------------------------------------------------------------------
# Logging estructurado (secciones pedidas en el spec)
# --------------------------------------------------------------------------

def log_search(keyword: str, location: str, results_found: int) -> None:
    logger.info("[SEARCH] Keyword: %s | Location: %s | Results found: %d", keyword, location, results_found)


def log_profile(url: str, name: Optional[str], rating: Optional[float], reviews: Optional[int], verified: bool) -> None:
    logger.info(
        "[PROFILE] URL: %s | Name: %s | Rating: %s | Reviews: %s | Verified: %s",
        url, name, rating, reviews, verified,
    )


def log_profile_error(url: str, status: str, error_type: Optional[str]) -> None:
    logger.warning("[PROFILE] URL: %s | status: %s | error_type: %s", url, status, error_type)


def log_score(name: Optional[str], score: float) -> None:
    logger.info("[SCORE] Name: %s | Score: %.2f", name, score)


def log_final(processed: int, successful: int, failed: int, dataset_records: int) -> None:
    logger.info(
        "[FINAL] Profiles processed: %d | Profiles successful: %d | Profiles failed: %d | Dataset records: %d",
        processed, successful, failed, dataset_records,
    )
