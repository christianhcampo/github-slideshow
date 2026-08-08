from src.normalizers import (
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


def test_normalize_name_collapses_whitespace():
    assert normalize_name("  Juan   Pérez  \n Plomería ") == "Juan Pérez Plomería"


def test_normalize_name_none():
    assert normalize_name(None) is None
    assert normalize_name("   ") is None


def test_normalize_url_removes_tracking_params():
    url = "https://example.com/perfil?utm_source=google&id=42&fbclid=abc"
    assert normalize_url(url) == "https://example.com/perfil?id=42"


def test_normalize_url_resolves_relative():
    assert normalize_url("/perfil/123", base_url="https://example.com/x/y") == "https://example.com/perfil/123"


def test_normalize_url_none():
    assert normalize_url(None) is None
    assert normalize_url("") is None


def test_normalize_location_strips_and_collapses():
    assert normalize_location("  Medellín ,  Colombia   ") == "Medellín , Colombia"


def test_normalize_location_none():
    assert normalize_location(None) is None


def test_normalize_rating_from_string():
    assert normalize_rating("4.8 de 5 estrellas") == 4.8


def test_normalize_rating_scale_of_ten():
    assert normalize_rating(9.6) == 4.8


def test_normalize_rating_caps_at_five():
    assert normalize_rating(4.99) == 4.99
    assert normalize_rating(5.0) == 5.0


def test_normalize_rating_none():
    assert normalize_rating(None) is None
    assert normalize_rating("sin calificación") is None


def test_normalize_review_count_from_text_with_thousands_separator():
    assert normalize_review_count("1,234 reseñas") == 1234


def test_normalize_review_count_plain_int():
    assert normalize_review_count(57) == 57


def test_normalize_review_count_none():
    assert normalize_review_count(None) is None
    assert normalize_review_count("sin reseñas") is None


def test_normalize_phone_strips_tel_prefix_and_symbols():
    assert normalize_phone("tel:+57 300 123 4567") == "+57 300 123 4567"


def test_normalize_phone_rejects_short_numbers():
    assert normalize_phone("12") is None


def test_normalize_phone_none():
    assert normalize_phone(None) is None


def test_normalize_images_dedupes_and_resolves():
    images = [
        "https://example.com/a.jpg",
        "/a.jpg",  # mismo recurso vía relativa -> distinta URL absoluta, no debería dedupear falsamente
        "https://example.com/a.jpg",  # duplicado exacto
        "",
        None,
    ]
    result = normalize_images(images, base_url="https://example.com/perfil")
    assert result.count("https://example.com/a.jpg") == 1
    assert "" not in result


def test_normalize_images_empty():
    assert normalize_images([]) == []
    assert normalize_images(None) == []


def test_normalize_email_valid():
    assert normalize_email("mailto:Contacto@Example.com") == "contacto@example.com"


def test_normalize_email_invalid():
    assert normalize_email("no-es-un-email") is None
    assert normalize_email(None) is None


def test_normalize_social_links_dedupes():
    links = ["https://instagram.com/x", "https://instagram.com/x?utm_source=ig"]
    result = normalize_social_links(links)
    assert result == ["https://instagram.com/x"]


def test_normalize_social_links_empty_returns_none():
    assert normalize_social_links([]) is None
    assert normalize_social_links(None) is None
