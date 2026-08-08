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

from crawlee import ConcurrencySettings
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.errors import HttpStatusCodeError, SessionError
from crawlee.storages import RequestQueue

from .extractors import extract_profile, domain_from_url
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
    ) -> None:
        self.concurrency = concurrency
        self.request_timeout_secs = request_timeout_secs
        self.max_retries = max_retries
        self.respect_robots = respect_robots
        self.headless = headless
        self.executable_path = executable_path or self._detect_executable_path()

    @staticmethod
    def _detect_executable_path() -> Optional[str]:
        env_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
        if env_path:
            return env_path
        if os.path.exists(DEFAULT_CHROMIUM_PATH):
            return DEFAULT_CHROMIUM_PATH
        return None

    async def scrape(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Visita cada URL y devuelve una lista de resultados (ok/blocked/error)."""
        if not urls:
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

        crawler = PlaywrightCrawler(
            request_manager=request_queue,
            max_requests_per_crawl=len(urls),
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

        @crawler.router.default_handler
        async def handler(context: PlaywrightCrawlingContext) -> None:
            url = context.request.url
            try:
                html = await context.page.content()
            except Exception as exc:  # HTML inválido / página rota
                results.append(
                    {
                        "profile_url": url,
                        "status": "error",
                        "error_type": "invalid_html",
                        "error": str(exc),
                        "scraped_at": _now_iso(),
                    }
                )
                log_profile_error(url, "error", "invalid_html")
                return

            http_status = context.response.status if context.response else None
            profile = extract_profile(html, url)
            record = {
                "profile_url": url,
                "domain": domain_from_url(url),
                "status": "ok",
                "error_type": None,
                "error": None,
                "http_status": http_status,
                "scraped_at": _now_iso(),
                **profile,
            }
            results.append(record)
            log_profile(url, profile.get("name"), profile.get("rating"), profile.get("review_count"), profile.get("verified"))

        @crawler.failed_request_handler
        async def failed_handler(context: PlaywrightCrawlingContext, error: Exception) -> None:
            url = context.request.url
            error_type = _classify_error(error)
            status = "blocked" if error_type in ("403", "429", "blocked") else "error"
            results.append(
                {
                    "profile_url": url,
                    "domain": domain_from_url(url),
                    "status": status,
                    "error_type": error_type,
                    "error": str(error)[:500],
                    "scraped_at": _now_iso(),
                }
            )
            log_profile_error(url, status, error_type)

        @crawler.on_skipped_request
        async def skipped_handler(url: str, reason: str) -> None:
            results.append(
                {
                    "profile_url": url,
                    "domain": domain_from_url(url),
                    "status": "blocked",
                    "error_type": reason,
                    "error": f"Request skipped: {reason}",
                    "scraped_at": _now_iso(),
                }
            )
            log_profile_error(url, "blocked", reason)

        try:
            await crawler.run(urls)
        except Exception as exc:
            logger.error("[PROFILE] Error inesperado del crawler: %s", exc)
        finally:
            await request_queue.drop()

        # Asegura que toda URL solicitada tenga al menos un resultado (por si el
        # crawler la descartó silenciosamente por alguna razón no capturada arriba).
        seen_urls = {r["profile_url"] for r in results}
        for url in urls:
            if url not in seen_urls:
                results.append(
                    {
                        "profile_url": url,
                        "domain": domain_from_url(url),
                        "status": "error",
                        "error_type": "not_processed",
                        "error": "La URL no fue procesada por el crawler.",
                        "scraped_at": _now_iso(),
                    }
                )

        return results
