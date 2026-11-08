"""Observe optional environment APIs without substituting page properties."""

from typing import Any

from playwright.async_api import Page


async def observe_extended(page: Page) -> dict[str, Any]:
    return await page.evaluate("""async () => {
        const posture = navigator.devicePosture;
        // The native DevicePosture service binds asynchronously after first access.
        if (posture) await new Promise(resolve => setTimeout(resolve, 80));
        const sample = document.createElement('div');
        sample.style.cssText = 'position:absolute;visibility:hidden;' +
            'width:calc(100px * env(preferred-text-scale, 1))';
        document.documentElement.appendChild(sample);
        const textScale = sample.getBoundingClientRect().width / 100;
        sample.remove();
        return {available_screen:{left:screen.availLeft, top:screen.availTop,
                    width:screen.availWidth, height:screen.availHeight},
            outer_window:{width:outerWidth,height:outerHeight},
            do_not_track:navigator.doNotTrack ?? null,
            global_privacy_control:navigator.globalPrivacyControl ?? null,
            save_data:navigator.connection?.saveData ?? null,
            text_scale:textScale, posture:posture?.type ?? null,
            segments:{horizontal:matchMedia('(horizontal-viewport-segments: 2)').matches,
                      vertical:matchMedia('(vertical-viewport-segments: 2)').matches}}
    }""")
