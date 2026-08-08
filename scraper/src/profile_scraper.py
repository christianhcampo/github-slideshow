"""Visita perfiles públicos con Playwright/Crawlee y extrae sus datos.

Maneja errores por página (403/404/429/timeout/bloqueo/HTML inválido) sin
detener el resto del crawl, respeta robots.txt, limita la concurrencia y
aplica timeouts + reintentos con backoff (delegado en Crawlee).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta, timezone, datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from crawlee import ConcurrencySettings, Request
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.errors import HttpStatusCodeError, SessionError
from crawlee.storages import RequestQueue

from .extractors import discover_internal_profile_links, domain_from_url, extract_profile
from .utils import log_profile, log_profile_error, logger

DEFAULT_CHROMIUM_PATH = "/opt/pw-browsers/chromium"


def _classify_error(error: Exception) -> str:
    if isinstance(error, HttpStatusCodeError):
        return str(error.status_code)
    if isinstance(error, SessionError):
        return "blocked"
    if isinstance(error, asyncio.TimeoutError):
        return "timeout"
    return type(error).__name__


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProfileScraper:
    """Encapsula el crawl de perfiles con Playwright/Crawlee."""

    def __init__(
        self,
        concurrency: int = 5,
        request_timeout_secs: int = 30,
        max_retries: int = 2,
        respect_robots: bool = True,
        headless: bool = True,
        executable_path: Optional[str] = None,
        max_profiles_per_site: int = 10,
    ) -> None:
        self.concurrency = concurrency
        self.request_timeout_secs = request_timeout_secs
        self.max_retries = max_retries
        self.respect_robots = respect_robots
        self.headless = headless
        self.executable_path = executable_path or self._detect_executable_path()
        self.max_profiles_per_site = max_profiles_per_site

    @staticmethod
    def _detect_executable_path() -> Optional[str]:
        env_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
        if env_path:
            return env_path
        if os.path.exists(DEFAULT_CHROMIUM_PATH):
            return DEFAULT_CHROMIUM_PATH
        return None

    async def scrape(self, seed_urls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Visita cada URL semilla y devuelve una lista de resultados (ok/blocked/error).

        Cada item de seed_urls es un dict con:
          - url (str, obligatorio)
          - google_position, search_title, search_description (opcionales, heredados
            del resultado de búsqueda que originó esa URL)

        Si una URL semilla resulta ser un directorio con varios perfiles internos,
        se detectan y visitan también esos sub-perfiles (un nivel de profundidad),
        heredando el mismo google_position/search_title/search_description y
        registrando de cuál página "directorio" (source_url) provienen.
        """
        if not seed_urls:
            return []

        results: List[Dict[str, Any]] = []

        browser_launch_options: Dict[str, Any] = {}
        if self.executable_path:
            browser_launch_options["executable_path"] = self.executable_path
        if os.geteuid() == 0:
            # Chromium se niega a lanzar en modo sandbox si el proceso corre como root
            # (habitual en contenedores). --no-sandbox es necesario en ese caso.
            browser_launch_options["args"] = ["--no-sandbox"]

        # Cola de requests aislada y efímera: evita que ejecuciones sucesivas (p. ej.
        # varias llamadas a scrape() en el mismo proceso) arrastren estado de una
        # cola "default" persistida en disco entre corridas.
        request_queue = await RequestQueue.open(alias=f"profiles-{uuid.uuid4().hex[:12]}")

        max_total_requests = len(seed_urls) * (1 + max(self.max_profiles_per_site, 0))

        crawler = PlaywrightCrawler(
            request_manager=request_queue,
            max_requests_per_crawl=max_total_requests,
            request_handler_timeout=timedelta(seconds=self.request_timeout_secs),
            max_request_retries=self.max_retries,
            concurrency_settings=ConcurrencySettings(
                max_concurrency=self.concurrency,
                desired_concurrency=min(self.concurrency, 10),
            ),
            respect_robots_txt_file=self.respect_robots,
            headless=self.headless,
            browser_launch_options=browser_launch_options or None,
        )

        def _record_base(url: str, user_data: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "profile_url": url,
                "domain": domain_from_url(url),
                "scraped_at": _now_iso(),
                "google_position": user_data.get("google_position"),
                "search_title": user_data.get("search_title"),
                "search_description": user_data.get("search_description"),
                "source_url": user_data.get("source_url"),
            }

        @crawler.router.default_handler
        async def handler(context: PlaywrightCrawlingContext) -> None:
            url = context.request.url
            user_data = dict(context.request.user_data or {})
            depth = user_data.get("depth", 0)

            try:
                html = await context.page.content()
            except Exception as exc:  # HTML inválido / página rota
                results.append(
                    {
                        **_record_base(url, user_data),
                        "status": "error",
                        "error_type": "invalid_html",
                        "error": str(exc),
                    }
                )
                log_profile_error(url, "error", "invalid_html")
                return

            http_status = context.response.status if context.response else None
            soup = BeautifulSoup(html or "", "html.parser")
            profile = extract_profile(html, url, soup=soup)
            record = {
                **_record_base(url, user_data),
                "status": "ok",
                "error_type": None,
                "error": None,
                "http_status": http_status,
                **profile,
            }
            results.append(record)
            log_profile(url, profile.get("name"), profile.get("rating"), profile.get("review_count"), profile.get("verified"))

            # Solo se busca un nivel de sub-perfiles (evita recursión descontrolada).
            if depth == 0 and self.max_profiles_per_site > 0:
                sub_links = discover_internal_profile_links(soup, url, max_links=self.max_profiles_per_site)
                if sub_links:
                    logger.info("[PROFILE] Directorio detectado en %s: %d sub-perfiles encontrados", url, len(sub_links))
                    sub_requests = [
                        Request.from_url(
                            link,
                            user_data={
                                "depth": 1,
                                "google_position": user_data.get("google_position"),
                                "search_title": user_data.get("search_title"),
                                "search_description": user_data.get("search_description"),
                                "source_url": url,
                            },
                        )
                        for link in sub_links
                    ]
                    await context.add_requests(sub_requests)

        @crawler.failed_request_handler
        async def failed_handler(context: PlaywrightCrawlingContext, error: Exception) -> None:
            url = context.request.url
            user_data = dict(context.request.user_data or {})
            error_type = _classify_error(error)
            status = "blocked" if error_type in ("403", "429", "blocked") else "error"
            results.append(
                {
                    **_record_base(url, user_data),
                    "status": status,
                    "error_type": error_type,
                    "error": str(error)[:500],
                }
            )
            log_profile_error(url, status, error_type)

        @crawler.on_skipped_request
        async def skipped_handler(url: str, reason: str) -> None:
            results.append(
                {
                    **_record_base(url, {}),
                    "status": "blocked",
                    "error_type": reason,
                    "error": f"Request skipped: {reason}",
                }
            )
            log_profile_error(url, "blocked", reason)

        initial_requests = [
            Request.from_url(
                item["url"],
                user_data={
                    "depth": 0,
                    "google_position": item.get("google_position"),
                    "search_title": item.get("search_title"),
                    "search_description": item.get("search_description"),
                    "source_url": None,
                },
            )
            for item in seed_urls
        ]

        try:
            await crawler.run(initial_requests)
        except Exception as exc:
            logger.error("[PROFILE] Error inesperado del crawler: %s", exc)
        finally:
            await request_queue.drop()

        # Asegura que toda URL semilla tenga al menos un resultado (por si el
        # crawler la descartó silenciosamente por alguna razón no capturada arriba).
        # No aplica a los sub-perfiles descubiertos dinámicamente, ya que no se
        # conocen de antemano.
        seen_urls = {r["profile_url"] for r in results}
        for item in seed_urls:
            if item["url"] not in seen_urls:
                results.append(
                    {
                        **_record_base(item["url"], item),
                        "status": "error",
                        "error_type": "not_processed",
                        "error": "La URL no fue procesada por el crawler.",
                    }
                )

        return results
