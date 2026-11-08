"""Optional environment smokes. Unsupported extensions do not hide a working engine."""

import asyncio
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from syntetic_core._engine.browser.extended_environment import observe_extended
from syntetic_core._engine.browser.factory import BrowserContextFactory
from syntetic_core._engine.browser.sensors import observe_sensors
from syntetic_core._engine.browser.visit_state import prepare_visit_state
from syntetic_core._engine.browser_runtime import RuntimeCapability, RuntimeWindowInsets
from syntetic_core._engine.config import Settings
from syntetic_core._engine.personas import (
    BrowserPersona,
    ChromiumExperience,
    FoldableDisplay,
    GeolocationConfig,
    NativeDesktopIdentity,
    SensorMotion,
    SitePreferences,
    VisitState,
)
from syntetic_core._engine.phone_personas import randomize_phone


async def verify_extensions(
    settings: Settings,
    persona: BrowserPersona,
    capability: RuntimeCapability,
    root: Path,
) -> None:
    headers: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            headers.append({key.lower(): value for key, value in self.headers.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            if self.path == "/experiment-payload":
                self.wfile.write(b"x" * 32768)
                return
            self.wfile.write(
                b'<meta name="viewport" content="width=device-width, initial-scale=1">'
                b'<script>localStorage.setItem("visited", "yes")</script>'
            )

        def log_message(self, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    settings = settings.model_copy(
        update={
            "allowed_target_hosts": ["127.0.0.1"],
            "trusted_local_target_hosts": ["127.0.0.1"],
            "allow_public_resources": False,
        }
    )

    async def probe(p: BrowserPersona, label: str, check: Any) -> None:
        async with asyncio.timeout(settings.browser_start_timeout + 15):
            factory = BrowserContextFactory(settings)
            async with factory.open(p, root / label / "1/browser-data") as context:
                await check(context, factory)

    try:

        async def geo_state(context: Any, factory: Any) -> None:
            await context.grant_permissions(["geolocation"], origin=url)
            page = await context.new_page()
            await page.goto(url)
            geo = await page.evaluate("""() => new Promise((resolve,reject) =>
                navigator.geolocation.getCurrentPosition(p => resolve(
                    [p.coords.latitude,p.coords.longitude,p.coords.accuracy]),
                    reject,{timeout:3000}))""")
            assert geo == [55.75, 37.62, 50]
            result = await prepare_visit_state(context, location, url, settings, 0)
            assert result["primer_visits"] == 1
            page = await context.new_page()
            await page.goto(url)
            assert await page.evaluate('localStorage.getItem("preference")') == "saved"
            assert any(c["name"] == "fixture-setting" for c in await context.cookies(url))
            from syntetic_core._engine.experiment_capabilities import verify_live

            await verify_live(context, location, capability, factory, url, settings)

        location = persona.model_copy(deep=True)
        location.geolocation = GeolocationConfig(latitude=55.75, longitude=37.62, accuracy=50)
        location.visit_state = VisitState(
            visitor="returning",
            cache="warm",
            preferences=[
                SitePreferences(
                    origin=url,
                    local_storage={"preference": "saved"},
                    cookies={"fixture-setting": "yes"},
                )
            ],
        )
        try:
            await probe(location, "geo-state", geo_state)
            capability.parameters.extend(["geolocation", "visit_state"])
            capability.parameters = list(dict.fromkeys(capability.parameters))
            if "geolocation" not in capability.permissions:
                capability.permissions.append("geolocation")
        except Exception:
            capability.limitations.append("Location/visitor-state extension smoke did not pass.")

        if persona.runtime.backend == "camoufox":
            from syntetic_core._engine.browser.media_presets import observe_media
            from syntetic_core._engine.browser_experiments import NativeMediaPreset

            try:
                for devices in ("none", "laptop", "conference"):
                    media = persona.model_copy(deep=True)
                    media.native_media = NativeMediaPreset(devices=devices, voices="none")

                    async def media_check(
                        context: Any, factory: Any, devices: str = devices
                    ) -> None:
                        page = await context.new_page()
                        await page.goto(url)
                        actual = await observe_media(page)
                        assert actual["voices"] == []
                        if devices == "none":
                            assert actual["devices"] == []
                        else:
                            assert sum(d["kind"] == "audioinput" for d in actual["devices"]) == 1

                    await probe(media, "media-" + devices, media_check)
                capability.parameters.append("native_media")
                capability.limitations.append(
                    "Media lists are masked before grants; camera/microphone grants "
                    "are not automated."
                )
            except Exception:
                capability.limitations.append("Native media presets smoke did not pass.")
            native = persona.model_copy(deep=True)
            native.device.viewport = {"width": 900, "height": 500}
            # This build's native chrome adds 85px on Linux. Verify it instead
            # of advertising geometry from the config keys alone.
            offset = 85 if capability.headful and __import__("platform").system() == "Linux" else 0
            native.native_desktop = NativeDesktopIdentity(
                avail_width=native.device.screen["width"],
                avail_height=native.device.screen["height"] - 48,
                outer_width=916,
                outer_height=590 + offset,
                config_height_offset=offset,
                do_not_track=True,
                global_privacy_control=True,
            )

            async def desktop_check(context: Any, factory: Any) -> None:
                headers.clear()
                page = await context.new_page()
                await page.goto(url)
                assert headers[-1].get("dnt") == "1" and headers[-1].get("sec-gpc") == "1"
                actual = await observe_extended(page)
                assert actual["do_not_track"] == "1" and actual["global_privacy_control"] is True

            try:
                await probe(native, "native-desktop", desktop_check)
                capability.window_insets = RuntimeWindowInsets(
                    width=16, height=90 + offset, config_height_offset=offset
                )
                capability.parameters.append("native_desktop")
            except Exception:
                capability.limitations.append("Native desktop geometry/privacy smoke did not pass.")

        if persona.browser_engine == "webkit":
            for seed in range(100):
                tablet = randomize_phone(persona, "ios", random.Random(seed), allow_tablets=True)
                if tablet.phone is not None and tablet.phone.form_factor == "tablet":
                    break

            async def tablet_check(context: Any, factory: Any) -> None:
                assert factory.connection["runtime"]["platform"] == "iPad"

            try:
                await probe(tablet, "tablet", tablet_check)
                capability.parameters.append("tablet_ios")
            except Exception:
                capability.limitations.append("iPad emulation smoke did not pass.")

        if persona.browser_engine == "chromium":
            experience = persona.model_copy(deep=True)
            assert experience.chromium is not None
            experience.chromium.experience = ChromiumExperience(
                text_scale=1.25, save_data=True, cpu_slowdown=2
            )

            async def experience_check(context: Any, factory: Any) -> None:
                page = await context.new_page()
                await page.goto(url)
                actual = await observe_extended(page)
                assert actual["save_data"] is True and abs(actual["text_scale"] - 1.3) < 0.01

            try:
                await probe(experience, "experience", experience_check)
                capability.parameters.append("chromium_experience")
            except Exception:
                capability.limitations.append(
                    "Text scale/data saver/CPU slowdown smoke did not pass."
                )
            if "virtual_sensors" in capability.parameters:
                from syntetic_core._engine.personas import StationarySensors

                phone = randomize_phone(persona, "android", random.Random(1))
                assert phone.chromium is not None
                phone.chromium.sensors = StationarySensors(roll=0, pitch=45, yaw=10)
                phone.chromium.motion = SensorMotion()

                async def motion_check(context: Any, factory: Any) -> None:
                    await context.grant_permissions(["accelerometer", "gyroscope"], origin=url)
                    page = await context.new_page()
                    await page.goto(url)
                    first = await observe_sensors(page)
                    await asyncio.sleep(0.5)
                    second = await observe_sensors(page)
                    assert first != second

                try:
                    await probe(phone, "motion", motion_check)
                    capability.parameters.append("sensor_motion")
                except Exception:
                    capability.limitations.append("Dynamic sensor smoke did not pass.")
            if "chromium_experience" in capability.parameters:
                for seed in range(100):
                    fold = randomize_phone(
                        persona, "android", random.Random(seed), allow_foldables=True
                    )
                    if fold.phone is not None and fold.phone.form_factor == "foldable":
                        break
                assert fold.chromium is not None and fold.phone is not None
                vertical = fold.phone.orientation == "portrait"
                fold.chromium.experience = ChromiumExperience(
                    foldable=FoldableDisplay(
                        offset=fold.device.viewport["width" if vertical else "height"] // 2,
                        orientation="vertical" if vertical else "horizontal",
                    )
                )

                async def fold_check(context: Any, factory: Any) -> None:
                    page = await context.new_page()
                    await page.goto(url)
                    await page.wait_for_function(
                        "navigator.devicePosture?.type === 'folded'", timeout=2000
                    )
                    actual = await observe_extended(page)
                    assert actual["segments"]["horizontal" if vertical else "vertical"] is True
                    assert actual["posture"] == "folded"

                try:
                    await probe(fold, "fold", fold_check)
                    capability.parameters.append("foldable")
                except Exception:
                    capability.limitations.append("Foldable posture/segments smoke did not pass.")
        from syntetic_core._engine.device_emulation_capabilities import verify_document_emulation

        await verify_document_emulation(persona, capability, probe, url, headers)
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)
