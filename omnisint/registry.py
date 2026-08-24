"""Which adapters exist, and which of them this machine can actually run."""
from __future__ import annotations

from .adapters.base import Adapter
from .adapters.darkweb import DarkWebAdapter
from .adapters.holehe import HoleheAdapter
from .adapters.maigret import MaigretAdapter
from .adapters.native import BreachAdapter, GravatarAdapter, InfrastructureAdapter
from .adapters.phone import PhoneAdapter, ToutatisAdapter
from .adapters.sherlock import SherlockAdapter
from .adapters.user_scanner import HudsonRockAdapter, UserScannerAdapter

ALL_ADAPTERS: tuple[type[Adapter], ...] = (
    MaigretAdapter,
    SherlockAdapter,
    UserScannerAdapter,
    HoleheAdapter,
    GravatarAdapter,
    ToutatisAdapter,
    HudsonRockAdapter,
    InfrastructureAdapter,
    PhoneAdapter,
    DarkWebAdapter,
    BreachAdapter,
)


def available_adapters(only: set[str] | None = None,
                       exclude: set[str] | None = None) -> list[type[Adapter]]:
    only = {o.lower() for o in (only or set())}
    exclude = {e.lower() for e in (exclude or set())}
    picked = []
    for cls in ALL_ADAPTERS:
        if only and cls.name.lower() not in only:
            continue
        # Opt-in adapters stay out unless named explicitly.
        if cls.opt_in and cls.name.lower() not in only:
            continue
        if cls.name.lower() in exclude:
            continue
        if not cls.available():
            continue
        picked.append(cls)
    return picked


def adapter_status() -> list[dict]:
    return [
        {
            "name": cls.name,
            "available": cls.available(),
            "path": cls.locate(),
            "accepts": [t.value for t in cls.accepts],
            "weight": cls.base_weight,
            "opt_in": cls.opt_in,
            "description": cls.description,
        }
        for cls in ALL_ADAPTERS
    ]
