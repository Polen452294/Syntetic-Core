"""Synthetic manifest for controller/unit tests; never used as browser acceptance evidence."""

from syntetic_core._engine.browser_runtime import CapabilityManifest, RuntimeCapability
from syntetic_core._engine.device_coherence import supported_recipe_ids


def manifest() -> dict:
    return CapabilityManifest(
        interaction_policy_version=2,
        operating_system="linux",
        architecture="x86_64",
        runtimes=[
            RuntimeCapability(
                backend=backend,
                engine=engine,
                browser_version="test",
                installed=True,
                smoke_test="passed",
                coherence_version=1,
                coherence_recipes=supported_recipe_ids(engine),
                device_sources=["desktop", "custom"],
                permissions=["geolocation"],
                parameters=[
                    "locale",
                    "timezone_id",
                    "viewport",
                    "screen",
                    "device_scale_factor",
                    "network",
                    "native_transport",
                    "session_api_policy_v1",
                    "persistent_storage",
                    "visit_state",
                    "geolocation",
                    "target_os",
                    "display_preferences",
                ]
                + (
                    ["phone_android", "hardware_concurrency", "virtual_sensors"]
                    if engine == "chromium"
                    else ["phone_ios", "webkit_full_native_v1"]
                    if engine == "webkit"
                    else ["native_audio"]
                ),
                diagnostic_adapters=["environment", "network"],
            )
            for backend, engine in [
                ("playwright", "chromium"),
                ("camoufox", "firefox"),
                ("playwright", "webkit"),
            ]
        ],
    ).model_dump(mode="json")
