"""The one browser configuration used by this project's new sessions."""

from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.personas import (
    BrowserPersona,
    DeviceConfig,
    NetworkPolicy,
    RuntimeConfig,
)

CONFIGURATION_NAME = "verified_camoufox_v1"
PROXY_ID = "pm-moscow-10453"
BROWSER_BUILD = "official/156.0.1-beta.35"
PROBE_URL = "https://api.ipify.org/?format=json"
# Exact service dependencies from the successful Pi probe; the project host is
# authorized separately. Keep native proxy DNS and browser cache as in that probe.
SERVICE_HOSTS = frozenset(
    {
        "ya.ru",
        "yandex.ru",
        "www.yandex.ru",
        "clck.yandex.ru",
        "sso.ya.ru",
        "sso.passport.yandex.ru",
        "yastatic.net",
        "avatars.mds.yandex.net",
        "mc.yandex.ru",
        "mc.yandex.md",
        "adfstat.yandex.ru",
        "captcha-backgrounds.s3.yandex.net",
        "cdnrhkgfkkpupuotntfj.svc.cdn.yandex.net",
        "market-click2.yandex.ru",
        "favicon.yandex.net",
        "hdrc.yandex.net",
        "mdd.yandex.net",
        "api.ipify.org",
    }
)
IDENTITY_FIELDS = {
    "id",
    "profile_id",
    "persona_revision",
    "config_hash",
    "fingerprint_id",
}


def session_persona(profile_id: int | str) -> BrowserPersona:
    """Identity is generated separately; browser/environment/network stay fixed."""
    from syntetic_core._engine.personas import MandatoryInteractionPolicy

    return BrowserPersona(
        id=str(profile_id),
        browser_engine="firefox",
        runtime=RuntimeConfig(backend="camoufox", headless=False),
        locale="ru-RU",
        timezone_id="Europe/Moscow",
        device=DeviceConfig(),
        proxy_id=PROXY_ID,
        network=NetworkPolicy(proxy_required=True, require_probe=True),
        interaction_policy=MandatoryInteractionPolicy(),
    )


def require_session_configuration(persona: BrowserPersona) -> None:
    expected = session_persona(persona.id)
    actual = persona.model_dump(mode="json", exclude=IDENTITY_FIELDS)
    fixed = expected.model_dump(mode="json", exclude=IDENTITY_FIELDS)
    changed = sorted(key for key in fixed if actual.get(key) != fixed[key])
    if changed:
        raise ProfileValidationError(
            "Проект использует только проверенную конфигурацию Camoufox. "
            "Создайте новый профиль; нельзя менять: " + ", ".join(changed)
        )
