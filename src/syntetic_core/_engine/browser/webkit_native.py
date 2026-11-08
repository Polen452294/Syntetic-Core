"""Verify unmodified WebKit media subsystems before installing document emulation."""

import asyncio
import base64
import io
import platform
import tempfile
import wave
from functools import cache
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page

from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.webkit_policy import WEBKIT_HOST_LIMITATION, webkit_host_allowed


@cache
def _samples() -> dict[str, str]:
    audio = io.BytesIO()
    with wave.open(audio, "wb") as sample:
        sample.setnchannels(1)
        sample.setsampwidth(2)
        sample.setframerate(8000)
        sample.writeframes(b"\0\0" * 800)
    video = Path(__file__).parent / "assets/webkit-native.mp4"
    return {
        "audio": base64.b64encode(audio.getvalue()).decode(),
        "video": base64.b64encode(video.read_bytes()).decode(),
    }


async def validate_webkit_native(
    context: BrowserContext, *, page: Page | None = None
) -> dict[str, Any]:
    system = platform.system()
    if not webkit_host_allowed(system):
        raise ProfileValidationError("runtime.webkit_host: " + WEBKIT_HOST_LIMITATION)
    # A local file is a trustworthy document without network interception. This check must
    # precede configure_session_apis so JS facades cannot supply the evidence.
    owns_page = page is None
    if page is None:
        page = await context.new_page()
    try:
        async with asyncio.timeout(15):
            with tempfile.TemporaryDirectory(prefix="webkit-native-") as directory:
                document = Path(directory) / "probe.html"
                document.write_text(
                    '<meta name="viewport" content="width=device-width,initial-scale=1">',
                    encoding="utf-8",
                )
                await page.goto(document.as_uri())
            actual = await page.evaluate(
                """async samples => {
                const checks = {
                    web_audio: typeof AudioContext === 'function' &&
                               typeof OfflineAudioContext === 'function',
                    media_devices: typeof navigator.mediaDevices?.enumerateDevices === 'function'
                        && typeof navigator.mediaDevices?.getUserMedia === 'function',
                    speech: typeof speechSynthesis !== 'undefined' &&
                            typeof speechSynthesis.getVoices === 'function',
                    audio_decode: false, video_decode: false, aac: false
                };
                if (checks.media_devices) {
                    const devices = await navigator.mediaDevices.enumerateDevices();
                    checks.media_devices = Array.isArray(devices);
                }
                if (checks.web_audio) {
                    const bytes = Uint8Array.from(atob(samples.audio), c => c.charCodeAt(0));
                    const offline = new OfflineAudioContext(1,800,8000);
                    const buffer = await offline.decodeAudioData(bytes.buffer);
                    checks.audio_decode = buffer.length > 0 && buffer.numberOfChannels === 1;
                }
                const video = document.createElement('video');
                video.muted = true; video.preload = 'auto';
                video.width = 32; video.height = 32; video.playsInline = true;
                checks.aac = document.createElement('audio')
                    .canPlayType('audio/mp4; codecs="mp4a.40.2"') !== '';
                if (video.canPlayType('video/mp4; codecs="avc1.42E01E, mp4a.40.2"')) {
                    document.body.append(video);
                    try {
                        checks.video_decode = await new Promise(resolve => {
                            const timer = setTimeout(() => resolve(false),8000);
                            video.onloadeddata = () => {
                                clearTimeout(timer);
                                resolve(video.readyState >= 2 && video.videoWidth === 32);
                            };
                            video.onerror = () => {clearTimeout(timer);resolve(false);};
                            video.src = 'data:video/mp4;base64,' + samples.video;
                            video.load();
                        });
                    } finally {
                        video.pause(); video.removeAttribute('src'); video.load(); video.remove();
                    }
                }
                return checks;
            }""",
                _samples(),
            )
        missing = [
            name
            for name in (
                "web_audio",
                "media_devices",
                "speech",
                "audio_decode",
                "video_decode",
                "aac",
            )
            if actual.get(name) is not True
        ]
        if missing:
            raise ProfileValidationError(
                "runtime.webkit_full_native: missing native subsystems: " + ", ".join(missing)
            )
        return {
            "version": 1,
            "host": "macos" if system == "Darwin" else "linux",
            "passed": True,
            "checks": actual,
        }
    except ProfileValidationError:
        raise
    except Exception as error:
        raise ProfileValidationError(
            "runtime.webkit_full_native: native media probe failed (" + type(error).__name__ + ")"
        ) from None
    finally:
        if owns_page:
            await page.close()
        elif not page.is_closed():
            await page.goto("about:blank")
