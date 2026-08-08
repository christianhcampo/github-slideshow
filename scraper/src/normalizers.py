"""Funciones de normalización de datos extraídos."""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urlparse, urlunparse, urljoin

from .utils import TRACKING_PARAMS


def normalize_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    cleaned = re.sub(r"\s+", " ", name).strip()
    return cleaned or None


def normalize_url(url: Optional[str], base_url: Optional[str] = None) -> Optional[str]:
    """Normaliza una URL: resuelve relativas contra base_url y limpia tracking params.

    No reordena ni elimina segmentos del path para no romper la página.
    """
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    if base_url:
        url = urljoin(base_url, url)
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    if not parsed.scheme or not parsed.netloc:
        return url
    return _safe_clean_url(parsed)


def _safe_clean_url(parsed) -> str:
    from urllib.parse import parse_qsl, urlencode

    query_pairs = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(query_pairs)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))


def normalize_location(location: Optional[str]) -> Optional[str]:
    if not location:
        return None
    cleaned = re.sub(r"\s+", " ", location).strip(" ,")
    return cleaned or None


def normalize_rating(rating) -> Optional[float]:
    if rating is None:
        return None
    if isinstance(rating, (int, float)):
        value = float(rating)
    else:
        match = re.search(r"(\d+(?:[.,]\d+)?)", str(rating))
        if not match:
            return None
        value = float(match.group(1).replace(",", "."))
    if value < 0:
        return None
    # Algunas páginas usan escalas de 0-10; si es mayor a 5 asumimos escala /10 y convertimos a /5.
    if value > 5 and value <= 10:
        value = round(value / 2, 2)
    return round(min(value, 5.0), 2)


def normalize_review_count(review_count) -> Optional[int]:
    if review_count is None:
        return None
    if isinstance(review_count, (int, float)):
        return max(int(review_count), 0)
    text = str(review_count)
    match = re.search(r"(\d[\d.,]*)", text)
    if not match:
        return None
    digits = re.sub(r"[.,](?=\d{3}(\D|$))", "", match.group(1))  # elimina separadores de miles
    digits = re.sub(r"[^\d]", "", digits)
    if not digits:
        return None
    return int(digits)


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    text = phone.strip()
    text = re.sub(r"^tel:", "", text, flags=re.IGNORECASE)
    # conserva un + inicial opcional, dígitos, espacios, guiones y paréntesis
    cleaned = re.sub(r"[^\d+ \-()]", "", text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    digits_only = re.sub(r"\D", "", cleaned)
    if len(digits_only) < 6:
        return None
    return cleaned or None


def normalize_images(images: Optional[List[str]], base_url: Optional[str] = None) -> List[str]:
    if not images:
        return []
    seen = set()
    result = []
    for img in images:
        if not img:
            continue
        normalized = normalize_url(img, base_url=base_url)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def normalize_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    text = email.strip()
    text = re.sub(r"^mailto:", "", text, flags=re.IGNORECASE)
    text = text.split("?")[0].strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text):
        return None
    return text.lower()


def normalize_social_links(links: Optional[List[str]]) -> Optional[List[str]]:
    if not links:
        return None
    seen = set()
    result = []
    for link in links:
        normalized = normalize_url(link)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result or None
