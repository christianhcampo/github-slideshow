from bs4 import BeautifulSoup

from src.extractors import (
    domain_from_url,
    extract_contact,
    extract_description,
    extract_images,
    extract_name,
    extract_profile,
    extract_rating_and_reviews,
    extract_verified,
    parse_json_ld_blocks,
)

JSON_LD_HTML = """
<html>
<head>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "LocalBusiness",
    "name": "Plomería El Rápido",
    "description": "Servicio de plomería residencial y comercial 24/7.",
    "address": {
        "@type": "PostalAddress",
        "streetAddress": "Cra 45 #10-20",
        "addressLocality": "Medellín",
        "addressCountry": "CO"
    },
    "aggregateRating": {
        "@type": "AggregateRating",
        "ratingValue": "4.8",
        "reviewCount": "325"
    },
    "image": ["https://example.com/img1.jpg", "https://example.com/img2.jpg"]
}
</script>
<meta property="og:title" content="OG Title (no debería usarse, JSON-LD tiene prioridad)">
</head>
<body>
<h1>No debería usarse (JSON-LD tiene prioridad)</h1>
</body>
</html>
"""

OG_FALLBACK_HTML = """
<html>
<head>
<meta property="og:title" content="Negocio Ejemplo">
<meta name="description" content="Descripción vía meta tag.">
<meta property="og:image" content="https://example.com/og-image.jpg">
</head>
<body>
<h1>Negocio Ejemplo</h1>
</body>
</html>
"""

VERIFIED_HTML = """
<html><body>
<span class="badge-verified">Perfil verificado</span>
</body></html>
"""

NOT_VERIFIED_HTML = """
<html><body>
<p>Este negocio tiene 500 reseñas y 4.9 de rating, muy popular.</p>
</body></html>
"""

CONTACT_HTML = """
<html><body>
<a href="tel:+573001234567">Llamar</a>
<a href="mailto:contacto@negocio.com">Escribir</a>
<a href="https://wa.me/573001234567">WhatsApp</a>
<a href="https://instagram.com/negocio">Instagram</a>
<a href="https://facebook.com/negocio">Facebook</a>
<a href="https://miweb.com/login">Login (no es contacto)</a>
</body></html>
"""

EMPTY_HTML = "<html><body><p>Página sin datos estructurados ni contacto.</p></body></html>"


def test_parse_json_ld_blocks():
    soup = BeautifulSoup(JSON_LD_HTML, "html.parser")
    blocks = parse_json_ld_blocks(soup)
    assert len(blocks) == 1
    assert blocks[0]["name"] == "Plomería El Rápido"


def test_extract_name_prefers_json_ld_over_h1():
    soup = BeautifulSoup(JSON_LD_HTML, "html.parser")
    json_ld = parse_json_ld_blocks(soup)
    assert extract_name(soup, json_ld) == "Plomería El Rápido"


def test_extract_name_falls_back_to_og_title():
    soup = BeautifulSoup(OG_FALLBACK_HTML, "html.parser")
    assert extract_name(soup, []) == "Negocio Ejemplo"


def test_extract_description_json_ld():
    soup = BeautifulSoup(JSON_LD_HTML, "html.parser")
    json_ld = parse_json_ld_blocks(soup)
    desc = extract_description(soup, json_ld)
    assert "plomería" in desc.lower()


def test_extract_description_meta_fallback():
    soup = BeautifulSoup(OG_FALLBACK_HTML, "html.parser")
    assert extract_description(soup, []) == "Descripción vía meta tag."


def test_extract_rating_and_reviews_json_ld():
    soup = BeautifulSoup(JSON_LD_HTML, "html.parser")
    json_ld = parse_json_ld_blocks(soup)
    rating, reviews = extract_rating_and_reviews(soup, json_ld)
    assert rating == "4.8"
    assert reviews == "325"


def test_extract_images_json_ld_and_og():
    soup = BeautifulSoup(JSON_LD_HTML, "html.parser")
    json_ld = parse_json_ld_blocks(soup)
    main_image, images = extract_images(soup, json_ld, base_url="https://example.com/perfil")
    assert main_image is not None
    assert "https://example.com/img1.jpg" in images
    assert "https://example.com/img2.jpg" in images


def test_extract_images_empty_when_no_images():
    soup = BeautifulSoup(EMPTY_HTML, "html.parser")
    main_image, images = extract_images(soup, [], base_url="https://example.com/perfil")
    assert main_image is None
    assert images == []


def test_extract_verified_true_on_explicit_badge():
    soup = BeautifulSoup(VERIFIED_HTML, "html.parser")
    assert extract_verified(soup) is True


def test_extract_verified_false_without_explicit_signal():
    """Muchas reseñas + rating alto NO deben contar como verificación."""
    soup = BeautifulSoup(NOT_VERIFIED_HTML, "html.parser")
    assert extract_verified(soup) is False


def test_extract_verified_false_on_empty_page():
    soup = BeautifulSoup(EMPTY_HTML, "html.parser")
    assert extract_verified(soup) is False


def test_extract_contact_public_links_only():
    soup = BeautifulSoup(CONTACT_HTML, "html.parser")
    contact = extract_contact(soup)
    assert contact["public_phone"] == "+573001234567"
    assert contact["public_email"] == "contacto@negocio.com"
    assert contact["public_whatsapp"] == "https://wa.me/573001234567"
    assert "https://instagram.com/negocio" in contact["public_social"]
    assert "https://facebook.com/negocio" in contact["public_social"]
    # El link de login no debe interpretarse como red social/contacto.
    assert all("login" not in s for s in contact["public_social"])


def test_extract_contact_all_none_when_absent():
    soup = BeautifulSoup(EMPTY_HTML, "html.parser")
    contact = extract_contact(soup)
    assert contact["public_phone"] is None
    assert contact["public_email"] is None
    assert contact["public_whatsapp"] is None
    assert contact["public_social"] == []


def test_extract_profile_missing_fields_return_none():
    profile = extract_profile(EMPTY_HTML, "https://example.com/perfil")
    assert profile["rating"] is None
    assert profile["review_count"] is None
    assert profile["location"] is None
    assert profile["images"] == []
    assert profile["verified"] is False


def test_extract_profile_full_json_ld():
    profile = extract_profile(JSON_LD_HTML, "https://example.com/perfil")
    assert profile["name"] == "Plomería El Rápido"
    assert profile["location"] == "Cra 45 #10-20, Medellín, CO"
    assert profile["rating"] == "4.8"
    assert profile["review_count"] == "325"


def test_domain_from_url():
    assert domain_from_url("https://www.example.com/perfil?x=1") == "example.com"
    assert domain_from_url("https://sub.example.com/perfil") == "sub.example.com"
