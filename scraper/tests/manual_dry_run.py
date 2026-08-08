"""Script de verificación manual end-to-end (no es parte de la suite pytest).

Levanta un servidor HTTP local que sirve las fixtures de tests/fixtures/site,
y corre el pipeline completo (search -> filter -> scrape -> normalize ->
score -> rank -> dataset) contra URLs locales controladas. Sirve para
comprobar, sin depender de red externa ni de una API key de Apify:

  1. Que el modo dry_run limita todo a 3 resultados/perfiles.
  2. Que el dataset final contiene datos.
  3. Que el ranking funciona (orden por score desc).
  4. Que las URLs duplicadas se eliminan.
  5. Que los campos inexistentes devuelven null/[].
  6. Que un error en una página (404) no detiene el crawl de las demás.
  7. Que las URLs irrelevantes (login, facebook, etc.) se filtran.

Uso:
    cd scraper && .venv/bin/python -m tests.manual_dry_run
"""
from __future__ import annotations

import asyncio
import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main import apply_dry_run_limits, run_pipeline  # noqa: E402
from src.models import SearchResult  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "site"


def start_server() -> tuple[socketserver.TCPServer, int]:
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *args, directory=str(FIXTURES_DIR), **kwargs
    )
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


async def scenario_dry_run(base_url: str) -> None:
    print("\n=== ESCENARIO 1: dry_run=true, 3 resultados (2 ok + 1 error 404) ===")
    seed = [
        SearchResult(position=1, title="Plomería El Rápido - Medellín", url=f"{base_url}/perfil1.html", description="Servicio de plomería 24/7"),
        SearchResult(position=2, title="Aseo y Limpieza Medellín", url=f"{base_url}/perfil2.html", description="Limpieza para hogares y oficinas"),
        SearchResult(position=3, title="Perfil inexistente", url=f"{base_url}/no-existe.html", description=None),
    ]
    actor_input = apply_dry_run_limits({
        "keyword": "servicios de limpieza",
        "location": "Medellín, Colombia",
        "maxSearchResults": 3,
        "maxProfiles": 3,
        "minRating": 0,
        "minReviews": 0,
        "onlyVerified": False,
        "dryRun": True,
    })
    records = await run_pipeline(actor_input, seed_results=seed)

    print(json.dumps(records, ensure_ascii=False, indent=2, default=str))

    assert len(records) == 3, f"Se esperaban 3 registros, hay {len(records)}"
    ok_records = [r for r in records if r["status"] == "ok"]
    error_records = [r for r in records if r["status"] == "error"]
    assert len(ok_records) == 2, "Deberían haber 2 perfiles OK"
    assert len(error_records) == 1, "Debería haber 1 perfil en error (404)"
    assert error_records[0]["error_type"] == "404"

    rankings = [r["ranking"] for r in ok_records]
    assert rankings == sorted(rankings), "El ranking debe estar ordenado"
    assert all(r > 0 for r in rankings)

    scores = [r["score"] for r in ok_records]
    assert scores == sorted(scores, reverse=True), "Los scores deben estar ordenados desc"

    p1 = next(r for r in ok_records if "perfil1" in r["profile_url"])
    assert p1["name"] == "Plomería El Rápido"
    assert p1["rating"] == 4.8
    assert p1["review_count"] == 325
    assert p1["verified"] is True
    assert p1["public_phone"] == "+573001234567"
    assert p1["public_email"] == "contacto@plomeriaelrapido.com"
    assert p1["public_whatsapp"] == "https://wa.me/573001234567"
    assert "https://example.com/img1.jpg" in p1["images"]

    p2 = next(r for r in ok_records if "perfil2" in r["profile_url"])
    assert p2["name"] == "Aseo y Limpieza Medellín"
    assert p2["verified"] is False  # sin señal explícita de verificación
    assert p2["public_phone"] is None  # no existe -> null
    assert p2["public_email"] is None
    assert p2["main_image"] == "https://example.com/aseo-og.jpg"

    print("OK: escenario dry_run superado.")


async def scenario_filtering_and_dedup(base_url: str) -> None:
    print("\n=== ESCENARIO 2: filtrado de URLs irrelevantes + deduplicación ===")
    seed = [
        SearchResult(position=1, title="Plomería El Rápido", url=f"{base_url}/perfil1.html", description="x"),
        SearchResult(position=2, title="Plomería El Rápido (dup)", url=f"{base_url}/perfil1.html?utm_source=google", description="x"),
        SearchResult(position=3, title="Google", url="https://www.google.com/search?q=plomeria", description="x"),
        SearchResult(position=4, title="Facebook", url="https://www.facebook.com/plomeria", description="x"),
        SearchResult(position=5, title="Login", url=f"{base_url}/login.html", description="x"),
        SearchResult(position=6, title="Aseo y Limpieza Medellín", url=f"{base_url}/perfil2.html", description="x"),
    ]
    actor_input = {
        "keyword": "servicios de limpieza",
        "location": "Medellín, Colombia",
        "maxSearchResults": 10,
        "maxProfiles": 10,
        "minRating": 0,
        "minReviews": 0,
        "onlyVerified": False,
        "dryRun": False,
    }
    records = await run_pipeline(actor_input, seed_results=seed)
    urls = [r["profile_url"] for r in records]
    print(json.dumps(urls, ensure_ascii=False, indent=2))

    assert len(records) == 2, f"Tras filtrar duplicados y URLs irrelevantes deberían quedar 2, hay {len(records)}"
    assert all("google.com" not in u and "facebook.com" not in u and "login" not in u for u in urls)
    print("OK: escenario de filtrado/dedup superado.")


async def main() -> None:
    httpd, port = start_server()
    base_url = f"http://127.0.0.1:{port}"
    print(f"Servidor local de fixtures en {base_url}")
    try:
        await scenario_dry_run(base_url)
        await scenario_filtering_and_dedup(base_url)
        print("\nTODOS LOS ESCENARIOS PASARON CORRECTAMENTE.")
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
