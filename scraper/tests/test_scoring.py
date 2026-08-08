from src.scoring import calculate_data_quality_score, calculate_score


def test_calculate_score_perfect_profile():
    score = calculate_score(rating=5.0, review_count=10_000, verified=True, google_position=1)
    assert score == 100.0


def test_calculate_score_no_data():
    score = calculate_score(rating=None, review_count=None, verified=False, google_position=None)
    assert score == 0.0


def test_calculate_score_massive_reviews_do_not_dominate():
    """10.000 reseñas no deben aportar mucho más que 1.000 gracias al log."""
    score_1000 = calculate_score(rating=4.5, review_count=1000, verified=False, google_position=None)
    score_10000 = calculate_score(rating=4.5, review_count=10_000, verified=False, google_position=None)
    score_100 = calculate_score(rating=4.5, review_count=100, verified=False, google_position=None)

    assert score_10000 > score_1000 > score_100

    # Un mismo incremento absoluto de reseñas (+1000) pesa mucho menos una vez
    # que ya hay muchas reseñas, gracias a la normalización logarítmica: el
    # salto de 100->1100 debe ser mayor que el de 9000->10000.
    score_1100 = calculate_score(rating=4.5, review_count=1100, verified=False, google_position=None)
    score_9000 = calculate_score(rating=4.5, review_count=9000, verified=False, google_position=None)
    low_range_gain = score_1100 - score_100
    high_range_gain = score_10000 - score_9000
    assert low_range_gain > high_range_gain


def test_calculate_score_verified_adds_25_points():
    base = calculate_score(rating=4.0, review_count=50, verified=False, google_position=None)
    with_verified = calculate_score(rating=4.0, review_count=50, verified=True, google_position=None)
    assert round(with_verified - base, 2) == 25.0


def test_calculate_score_google_position_decreases():
    pos1 = calculate_score(rating=4.0, review_count=0, verified=False, google_position=1)
    pos5 = calculate_score(rating=4.0, review_count=0, verified=False, google_position=5)
    pos20 = calculate_score(rating=4.0, review_count=0, verified=False, google_position=20)
    assert pos1 > pos5 > pos20
    assert pos20 == calculate_score(rating=4.0, review_count=0, verified=False, google_position=None)


def test_calculate_score_is_rounded_to_two_decimals():
    score = calculate_score(rating=4.33, review_count=17, verified=True, google_position=3)
    assert score == round(score, 2)


def test_calculate_score_bounded_between_0_and_100():
    score = calculate_score(rating=5.0, review_count=1_000_000, verified=True, google_position=1)
    assert 0.0 <= score <= 100.0


def test_data_quality_score_full_profile():
    profile = {
        "name": "Plomería Rápida",
        "images": ["https://example.com/1.jpg"],
        "description": "Servicio de plomería 24/7",
        "location": "Medellín, Colombia",
        "rating": 4.5,
        "review_count": 30,
        "verified": True,
        "public_phone": "+57 300 000 0000",
        "public_whatsapp": None,
        "public_email": None,
        "public_social": None,
        "profile_url": "https://example.com/perfil",
    }
    assert calculate_data_quality_score(profile) == 100.0


def test_data_quality_score_empty_profile():
    profile = {
        "name": None,
        "images": [],
        "description": None,
        "location": None,
        "rating": None,
        "review_count": None,
        "verified": False,
        "public_phone": None,
        "public_whatsapp": None,
        "public_email": None,
        "public_social": None,
        "profile_url": "https://example.com/perfil",
    }
    # Solo profile_url está presente -> peso 15/100
    assert calculate_data_quality_score(profile) == 15.0


def test_data_quality_score_partial_profile():
    profile = {
        "name": "Negocio X",
        "images": [],
        "description": None,
        "location": "Bogotá",
        "rating": None,
        "review_count": None,
        "verified": False,
        "public_phone": None,
        "public_whatsapp": None,
        "public_email": None,
        "public_social": None,
        "profile_url": "https://example.com/perfil",
    }
    score = calculate_data_quality_score(profile)
    assert 0 < score < 100
