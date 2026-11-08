"""Actual browser checks for opt-in live conditions on the worker's local fixture."""

import asyncio
from time import monotonic
from typing import Any

from syntetic_core._engine.browser.experiment import VisitExperiment
from syntetic_core._engine.browser_experiments import (
    BrowserExperiment,
    DisplayCondition,
    NetworkCondition,
)


class Sink:
    async def emit(self, *_args: Any, **_kwargs: Any) -> None:
        pass


async def verify_live(
    context: Any, persona: Any, capability: Any, factory: Any, url: str, settings: Any
) -> None:
    page = await context.new_page()
    await page.goto(url)
    prefix = "mw:" if persona.runtime.backend == "camoufox" else ""
    initial_online = await page.evaluate(prefix + "navigator.onLine")
    expected = dict(factory.connection["runtime"])
    timeline = VisitExperiment(
        context,
        persona.model_copy(deep=True),
        url,
        settings,
        factory,
        Sink(),
        expected,
        asyncio.Lock(),
    )
    try:
        factory.target_proxy.pacer.set(NetworkCondition(download_kbps=256, latency_ms=30))
        started = monotonic()
        size = await page.evaluate(
            prefix
            + """async url =>
            (await (await fetch(url)).arrayBuffer()).byteLength""",
            url + "/experiment-payload",
        )
        assert size == 32768 and monotonic() - started >= 0.8
        capability.parameters.append("network_shaping")
    except Exception:
        capability.limitations.append("Per-session TCP shaping smoke did not pass.")
    finally:
        factory.target_proxy.pacer.set(NetworkCondition())

    live = persona.model_copy(deep=True)
    live.experiment = BrowserExperiment.model_validate(
        {
            "events": [
                {"kind": "network", "offline": True},
                {"kind": "network", "after_ms": 100},
                {"kind": "location", "after_ms": 150, "latitude": 55.76, "longitude": 37.63},
                {
                    "kind": "storage",
                    "after_ms": 200,
                    "remove_local_storage": ["preference"],
                    "remove_cookies": ["fixture-setting"],
                },
                {"kind": "history", "after_ms": 250, "direction": "reload"},
            ]
        }
    )
    run = VisitExperiment(context, live, url, settings, factory, Sink(), expected, asyncio.Lock())
    try:
        run.start()
        assert run.task is not None
        await asyncio.wait_for(asyncio.shield(run.task), timeout=5)
        await run.close()
        assert run.applied == 5
        # An isolated container may have no physical network interface. Clearing
        # the native offline override restores that baseline, not always `true`.
        assert await page.evaluate(prefix + "navigator.onLine") == initial_online
        capability.parameters.append("visit_timeline")
    except Exception as exc:
        capability.limitations.append(
            f"Live visitor smoke failed after {run.applied} events ({type(exc).__name__})."
        )
    finally:
        factory.target_proxy.pacer.set(NetworkCondition())
        await context.set_offline(False)
    if persona.runtime.backend != "camoufox":
        try:
            await timeline.display(
                page, DisplayCondition(width=720, height=480, orientation="landscape")
            )
            assert await page.evaluate("innerWidth") == 720
            capability.parameters.append("dynamic_viewport")
        except Exception:
            capability.limitations.append("Dynamic viewport smoke did not pass.")
    if persona.browser_engine == "chromium":
        checks: list[tuple[str, dict[str, Any], str, Any]] = [
            (
                "safe_area",
                {"safe_area": {"top": 27}},
                """() => {
                const e=document.createElement('div');e.style.paddingTop='env(safe-area-inset-top)';
                document.body.appendChild(e);const v=getComputedStyle(e).paddingTop;e.remove();
                return v;}""",
                "27px",
            ),
            ("page_scale", {"page_scale": 1.25}, "visualViewport.scale", 1.25),
            (
                "native_keyboard",
                {"keyboard": {"mode": "native", "width": 720, "height": 150, "y": 330}},
                "navigator.virtualKeyboard.boundingRect.height",
                150,
            ),
        ]
        for parameter, extra, script, value in checks:
            try:
                await timeline.display(
                    page,
                    DisplayCondition.model_validate(
                        {"width": 720, "height": 480, "orientation": "landscape", **extra}
                    ),
                )
                assert await page.evaluate(script) == value
                capability.parameters.append(parameter)
            except Exception:
                capability.limitations.append(parameter + " native smoke did not pass.")
