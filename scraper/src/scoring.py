"""Cálculo de score y data_quality_score para los perfiles."""
from __future__ import annotations

import math
from typing import Optional

# Un review_count "de referencia" a partir del cual la escala logarítmica
# se acerca a su máximo, para que 10.000 reviews no dominen el score.
REVIEW_LOG_REFERENCE = 10_000


def _normalized_log_reviews(review_count: Optional[int]) -> float:
    if not review_count or review_count <= 0:
        return 0.0
    value = math.log10(review_count + 1) / math.log10(REVIEW_LOG_REFERENCE + 1)
    return min(value, 1.0)


def _google_position_score(position: Optional[int]) -> float:
    """10 puntos para la posición 1, decreciendo hasta 0 en posiciones bajas."""
    if not position or position < 1:
        return 0.0
    if position > 10:
        return 0.0
    return float(11 - position)


def calculate_score(
    rating: Optional[float],
    review_count: Optional[int],
    verified: bool,
    google_position: Optional[int],
) -> float:
    """Score 0-100. rating=40%, reviews(log)=25%, verified=25%, google_position=10%."""
    rating_score = ((rating or 0.0) / 5.0) * 40
    review_score = _normalized_log_reviews(review_count) * 25
    verified_score = 25.0 if verified else 0.0
    google_score = _google_position_score(google_position)

    score = rating_score + review_score + verified_score + google_score
    return round(min(max(score, 0.0), 100.0), 2)


def calculate_data_quality_score(profile: dict) -> float:
    """Evalúa qué tan completo está el perfil extraído, 0-100.

    Cada campo pesa igual. Campos que naturalmente pueden no existir
    (rating, review_count, contacto) restan menos si faltan.
    """
    weights = {
        "name": 15,
        "images": 10,
        "description": 10,
        "location": 10,
        "rating": 10,
        "review_count": 10,
        "verified": 5,
        "contact": 15,
        "profile_url": 15,
    }
    total_weight = sum(weights.values())
    earned = 0.0

    if profile.get("name"):
        earned += weights["name"]
    if profile.get("images"):
        earned += weights["images"]
    if profile.get("description"):
        earned += weights["description"]
    if profile.get("location"):
        earned += weights["location"]
    if profile.get("rating") is not None:
        earned += weights["rating"]
    if profile.get("review_count") is not None:
        earned += weights["review_count"]
    # "verified" siempre tiene un valor (True/False), así que se cuenta como presente
    # solo cuando es True (una señal explícita fue detectada).
    if profile.get("verified"):
        earned += weights["verified"]
    if profile.get("public_phone") or profile.get("public_whatsapp") or profile.get("public_email") or profile.get("public_social"):
        earned += weights["contact"]
    if profile.get("profile_url"):
        earned += weights["profile_url"]

    return round((earned / total_weight) * 100, 2)
