"""Syntetic Core: stable device profiles and native browser automation."""

from syntetic_core._engine.config import Settings as CoreSettings
from syntetic_core._engine.errors import ProfileLockedError, ProfileValidationError
from syntetic_core._engine.personas import BrowserPersona
from syntetic_core._engine.proxies import ProxyConfig
from syntetic_core.core import BrowserSession, SynteticCore
from syntetic_core.proxy import HttpRotationProvider, RotationProvider, RotationResult

__all__ = [
    "BrowserPersona",
    "BrowserSession",
    "CoreSettings",
    "HttpRotationProvider",
    "ProfileLockedError",
    "ProfileValidationError",
    "ProxyConfig",
    "RotationProvider",
    "RotationResult",
    "SynteticCore",
]
__version__ = "0.1.0"
