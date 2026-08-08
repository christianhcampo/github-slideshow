"""Extracción robusta de datos de perfil desde HTML.

Estrategia en cascada, en orden de prioridad:
1. JSON-LD
2. Schema.org (microdata básica)
3. Open Graph
4. Meta tags
5. HTML semántico
6. Selectores específicos conocidos
7. Fallback basado en estructura DOM

Cada función intenta cada estrategia en orden y devuelve el primer valor
no vacío que encuentre. Si nada funciona, devuelve None (nunca se inventa
un valor).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

VERIFIED_PATTERNS = [
    r"\bverified\b",
    r"perfil\s+verificado",
    r"usuario\s+verificado",
    r"cuenta\s+verificada",
    r"✓\s*verificado",
    r"\bverificado\b",
]

RATING_LABEL_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:/\s*5|de\s*5|estrellas|stars)?", re.IGNORECASE)
REVIEW_LABEL_PATTERN = re.compile(r"(\d[\d.,]*)\s*(?:reseñas|reviews|opiniones|calificaciones)", re.IGNORECASE)
LOCATION_LABEL_PATTERN = re.compile(r"(ubicaci[oó]n|direcci[oó]n|address|location)\s*[:\-]?\s*(.+)", re.IGNORECASE)


# --------------------------------------------------------------------------
# JSON-LD
# --------------------------------------------------------------------------

def parse_json_ld_blocks(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Devuelve todos los objetos JSON-LD encontrados en la página (aplanados)."""
    blocks: List[Dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, list):
            for item in data:
                blocks.extend(_flatten_json_ld(item))
        else:
            blocks.extend(_flatten_json_ld(data))
    return blocks


def _flatten_json_ld(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    result = [data]
    graph = data.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            result.extend(_flatten_json_ld(item))
    return result


def _first_json_ld_with_key(blocks: List[Dict[str, Any]], keys: List[str]) -> Optional[Dict[str, Any]]:
    for block in blocks:
        if any(k in block for k in keys):
            return block
    return None


# --------------------------------------------------------------------------
# Nombre
# --------------------------------------------------------------------------

def extract_name(soup: BeautifulSoup, json_ld: List[Dict[str, Any]]) -> Optional[str]:
    block = _first_json_ld_with_key(json_ld, ["name"])
    if block and isinstance(block.get("name"), str) and block["name"].strip():
        return block["name"].strip()

    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)

    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content", "").strip():
        return og_title["content"].strip()

    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)

    return None


# --------------------------------------------------------------------------
# Descripción
# --------------------------------------------------------------------------

def extract_description(soup: BeautifulSoup, json_ld: List[Dict[str, Any]]) -> Optional[str]:
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content", "").strip():
        return meta_desc["content"].strip()

    og_desc = soup.find("meta", attrs={"property": "og:description"})
    if og_desc and og_desc.get("content", "").strip():
        return og_desc["content"].strip()

    block = _first_json_ld_with_key(json_ld, ["description"])
    if block and isinstance(block.get("description"), str) and block["description"].strip():
        return block["description"].strip()

    for tag_name in ("p", "div"):
        for candidate in soup.find_all(tag_name, attrs={"class": re.compile("descrip", re.I)}):
            text = candidate.get_text(strip=True)
            if text and len(text) > 20:
                return text

    return None


# --------------------------------------------------------------------------
# Ubicación
# --------------------------------------------------------------------------

def extract_location(soup: BeautifulSoup, json_ld: List[Dict[str, Any]]) -> Optional[str]:
    block = _first_json_ld_with_key(json_ld, ["address"])
    if block:
        address = block.get("address")
        location = _address_to_string(address)
        if location:
            return location

    for attr_name, attr_value in (
        ("itemprop", "address"),
        ("class", re.compile("address|location|ubicacion", re.I)),
    ):
        el = soup.find(attrs={attr_name: attr_value})
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)

    for el in soup.find_all(["span", "div", "p", "li"]):
        text = el.get_text(" ", strip=True)
        if not text or len(text) > 200:
            continue
        match = LOCATION_LABEL_PATTERN.match(text)
        if match:
            candidate = match.group(2).strip()
            if candidate:
                return candidate

    return None


def _address_to_string(address: Any) -> Optional[str]:
    if isinstance(address, str):
        return address.strip() or None
    if isinstance(address, dict):
        parts = [
            address.get("streetAddress"),
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("addressCountry"),
        ]
        parts = [p for p in parts if isinstance(p, str) and p.strip()]
        return ", ".join(parts) if parts else None
    return None


# --------------------------------------------------------------------------
# Rating / Reviews
# --------------------------------------------------------------------------

def extract_rating_and_reviews(
    soup: BeautifulSoup, json_ld: List[Dict[str, Any]]
) -> Tuple[Optional[Any], Optional[Any]]:
    rating: Optional[Any] = None
    reviews: Optional[Any] = None

    block = _first_json_ld_with_key(json_ld, ["aggregateRating"])
    if block:
        agg = block.get("aggregateRating")
        if isinstance(agg, dict):
            rating = agg.get("ratingValue", rating)
            reviews = agg.get("reviewCount") or agg.get("ratingCount") or reviews

    if rating is None:
        rating_el = soup.find(attrs={"itemprop": "ratingValue"})
        if rating_el:
            rating = rating_el.get("content") or rating_el.get_text(strip=True)

    if reviews is None:
        reviews_el = soup.find(attrs={"itemprop": re.compile("reviewCount|ratingCount")})
        if reviews_el:
            reviews = reviews_el.get("content") or reviews_el.get_text(strip=True)

    if rating is None:
        el = soup.find(attrs={"class": re.compile(r"\brating\b", re.I)})
        if el:
            text = el.get_text(" ", strip=True)
            match = RATING_LABEL_PATTERN.search(text)
            if match:
                rating = match.group(1)

    if reviews is None:
        for el in soup.find_all(["span", "div", "p"]):
            text = el.get_text(" ", strip=True)
            if not text or len(text) > 100:
                continue
            match = REVIEW_LABEL_PATTERN.search(text)
            if match:
                reviews = match.group(1)
                break

    return rating, reviews


# --------------------------------------------------------------------------
# Imágenes
# --------------------------------------------------------------------------

def extract_images(
    soup: BeautifulSoup, json_ld: List[Dict[str, Any]], base_url: str
) -> Tuple[Optional[str], List[str]]:
    images: List[str] = []

    og_image = soup.find("meta", attrs={"property": "og:image"})
    if og_image and og_image.get("content", "").strip():
        images.append(urljoin(base_url, og_image["content"].strip()))

    block = _first_json_ld_with_key(json_ld, ["image"])
    if block:
        image_field = block.get("image")
        for url in _flatten_image_field(image_field):
            images.append(urljoin(base_url, url))

    for img_tag in soup.find_all("img"):
        src = img_tag.get("src") or img_tag.get("data-src")
        if src and not src.startswith("data:"):
            images.append(urljoin(base_url, src))
        srcset = img_tag.get("srcset")
        if srcset:
            first_candidate = srcset.split(",")[0].strip().split(" ")[0]
            if first_candidate and not first_candidate.startswith("data:"):
                images.append(urljoin(base_url, first_candidate))

    # Dedup preservando orden
    seen = set()
    unique_images = []
    for img in images:
        if img not in seen:
            seen.add(img)
            unique_images.append(img)

    main_image = unique_images[0] if unique_images else None
    return main_image, unique_images


def _flatten_image_field(image_field: Any) -> List[str]:
    if isinstance(image_field, str):
        return [image_field]
    if isinstance(image_field, list):
        result = []
        for item in image_field:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict) and isinstance(item.get("url"), str):
                result.append(item["url"])
        return result
    if isinstance(image_field, dict) and isinstance(image_field.get("url"), str):
        return [image_field["url"]]
    return []


# --------------------------------------------------------------------------
# Verificación
# --------------------------------------------------------------------------

def extract_verified(soup: BeautifulSoup) -> bool:
    """Solo True si hay una señal EXPLÍCITA de verificación en el texto/atributos."""
    for el in soup.find_all(attrs={"class": re.compile("verif", re.I)}):
        text = el.get_text(" ", strip=True)
        if _matches_verified_pattern(text):
            return True

    for el in soup.find_all(attrs={"aria-label": re.compile("verif", re.I)}):
        if _matches_verified_pattern(el.get("aria-label", "")):
            return True

    body_text = soup.get_text(" ", strip=True)
    if _matches_verified_pattern(body_text, allow_full_text=False):
        return True

    return False


def _matches_verified_pattern(text: str, allow_full_text: bool = True) -> bool:
    if not text:
        return False
    normalized = text.lower()
    for pattern in VERIFIED_PATTERNS:
        if re.search(pattern, normalized):
            # Evita falsos positivos si el texto es demasiado largo (probablemente
            # es el body completo y no una etiqueta/badge específica).
            if allow_full_text or len(text) <= 60:
                return True
    return False


# --------------------------------------------------------------------------
# Contacto público
# --------------------------------------------------------------------------

def extract_contact(soup: BeautifulSoup) -> Dict[str, Any]:
    phone = None
    whatsapp = None
    email = None
    social: List[str] = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        lower = href.lower()

        if lower.startswith("tel:") and not phone:
            phone = href[4:]
            continue

        if lower.startswith("mailto:") and not email:
            email = href[7:]
            continue

        if "wa.me" in lower or "whatsapp.com" in lower or "api.whatsapp.com" in lower:
            if not whatsapp:
                whatsapp = href
            continue

        for social_domain in ("instagram.com", "facebook.com", "twitter.com", "x.com", "tiktok.com", "youtube.com", "linkedin.com"):
            if social_domain in lower:
                social.append(href)
                break

    return {
        "public_phone": phone,
        "public_whatsapp": whatsapp,
        "public_email": email,
        "public_social": social,
    }


# --------------------------------------------------------------------------
# Extracción completa de un perfil
# --------------------------------------------------------------------------

def extract_profile(html: str, url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    json_ld = parse_json_ld_blocks(soup)

    name = extract_name(soup, json_ld)
    description = extract_description(soup, json_ld)
    location = extract_location(soup, json_ld)
    rating, review_count = extract_rating_and_reviews(soup, json_ld)
    main_image, images = extract_images(soup, json_ld, base_url=url)
    verified = extract_verified(soup)
    contact = extract_contact(soup)

    return {
        "name": name,
        "description": description,
        "location": location,
        "rating": rating,
        "review_count": review_count,
        "verified": verified,
        "main_image": main_image,
        "images": images,
        **contact,
    }


def domain_from_url(url: str) -> Optional[str]:
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or None
