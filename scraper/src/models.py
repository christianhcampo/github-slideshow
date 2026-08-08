"""Modelos de datos usados en todo el pipeline de scraping."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Any, Dict


@dataclass
class SearchResult:
    """Un resultado orgánico de búsqueda."""

    position: int
    title: Optional[str]
    url: str
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProfileRecord:
    """Registro final de un perfil, listo para el Dataset de salida."""

    profile_url: str
    domain: Optional[str] = None
    status: str = "ok"  # ok | blocked | error | filtered
    error_type: Optional[str] = None
    error: Optional[str] = None

    name: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    verified: bool = False

    main_image: Optional[str] = None
    images: List[str] = field(default_factory=list)

    public_phone: Optional[str] = None
    public_whatsapp: Optional[str] = None
    public_email: Optional[str] = None
    public_social: Optional[List[str]] = None

    google_position: Optional[int] = None
    search_title: Optional[str] = None
    search_description: Optional[str] = None

    scraped_at: Optional[str] = None

    score: Optional[float] = None
    data_quality_score: Optional[float] = None
    ranking: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RawProfileData:
    """Datos crudos extraídos de una página, antes de normalizar."""

    name: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    rating: Optional[Any] = None
    review_count: Optional[Any] = None
    verified: bool = False
    main_image: Optional[str] = None
    images: List[str] = field(default_factory=list)
    public_phone: Optional[str] = None
    public_whatsapp: Optional[str] = None
    public_email: Optional[str] = None
    public_social: List[str] = field(default_factory=list)
