"""Proveedores de resultados de búsqueda (SERP).

No se hace scraping directo de Google. Los resultados orgánicos se obtienen
mediante un Actor/API de Apify (o cualquier otro proveedor SERP que se
conecte aquí), configurado por variables de entorno. Nunca se hardcodean
API keys.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import List, Optional

from .models import SearchResult
from .utils import logger


class SearchProvider(ABC):
    """Interfaz abstracta para obtener resultados de búsqueda orgánicos."""

    @abstractmethod
    def search(self, keyword: str, location: str, max_results: int) -> List[SearchResult]:
        """Devuelve una lista de resultados orgánicos para keyword + location."""
        raise NotImplementedError


class ApifySearchProvider(SearchProvider):
    """Adaptador que usa un Actor de Apify (p. ej. un SERP scraper) como
    proveedor de resultados de búsqueda, evitando el scraping directo de Google.

    Requiere las variables de entorno:
      - APIFY_API_TOKEN
      - SEARCH_ACTOR_ID (por defecto "apify/google-search-scraper")
    """

    DEFAULT_ACTOR_ID = "apify/google-search-scraper"

    def __init__(self, api_token: Optional[str] = None, actor_id: Optional[str] = None):
        self.api_token = api_token or os.environ.get("APIFY_API_TOKEN")
        self.actor_id = actor_id or os.environ.get("SEARCH_ACTOR_ID", self.DEFAULT_ACTOR_ID)
        if not self.api_token:
            raise ValueError(
                "APIFY_API_TOKEN no está configurado. Define esta variable de entorno "
                "(ver .env.example) para usar ApifySearchProvider."
            )

    def search(self, keyword: str, location: str, max_results: int) -> List[SearchResult]:
        from apify_client import ApifyClient  # import diferido: opcional para uso local

        client = ApifyClient(self.api_token)
        query = f"{keyword} {location}".strip()
        run_input = {
            "queries": query,
            "maxPagesPerQuery": 1,
            "resultsPerPage": max_results,
            "countryCode": "",
            "languageCode": "",
        }

        logger.info("[SEARCH] Ejecutando actor SERP '%s' en Apify...", self.actor_id)
        run = client.actor(self.actor_id).call(run_input=run_input)
        dataset_id = run["defaultDatasetId"] if isinstance(run, dict) else run.default_dataset_id

        results: List[SearchResult] = []
        position = 0
        for item in client.dataset(dataset_id).iterate_items():
            organic_results = item.get("organicResults") or item.get("results") or []
            for entry in organic_results:
                if position >= max_results:
                    break
                position += 1
                results.append(
                    SearchResult(
                        position=entry.get("position", position),
                        title=entry.get("title"),
                        url=entry.get("url") or entry.get("link"),
                        description=entry.get("description") or entry.get("snippet"),
                    )
                )
            if position >= max_results:
                break

        return [r for r in results if r.url]


class StaticSearchProvider(SearchProvider):
    """Proveedor que devuelve una lista de resultados fija/pre-cargada.

    Útil para pruebas locales (dry_run) sin depender de una API externa,
    o para inyectar URLs conocidas manualmente.
    """

    def __init__(self, results: List[SearchResult]):
        self._results = results

    def search(self, keyword: str, location: str, max_results: int) -> List[SearchResult]:
        return self._results[:max_results]


def get_search_provider(seed_results: Optional[List[SearchResult]] = None) -> SearchProvider:
    """Factory: elige el proveedor según configuración disponible.

    - Si se pasan seed_results explícitos (p. ej. en tests/dry_run local), se usa StaticSearchProvider.
    - Si hay APIFY_API_TOKEN configurado, se usa ApifySearchProvider.
    - En otro caso, lanza un error claro explicando qué falta.
    """
    if seed_results is not None:
        return StaticSearchProvider(seed_results)

    if os.environ.get("APIFY_API_TOKEN"):
        return ApifySearchProvider()

    raise ValueError(
        "No hay proveedor de búsqueda configurado. Define APIFY_API_TOKEN y opcionalmente "
        "SEARCH_ACTOR_ID (ver .env.example), o provee seed_results para pruebas locales."
    )
Fix Run object access
