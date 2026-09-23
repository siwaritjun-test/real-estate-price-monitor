"""Registry of available source adapters."""

from __future__ import annotations

from .base import Source, SourceResult
from .ddproperty import DDProperty
from .hipflat import Hipflat
from .livinginsider import LivingInsider

REGISTRY: dict[str, type[Source]] = {
    cls.name: cls for cls in (DDProperty, LivingInsider, Hipflat)
}

__all__ = ["REGISTRY", "Source", "SourceResult"]
