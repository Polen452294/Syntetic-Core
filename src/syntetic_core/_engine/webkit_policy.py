"""Host policy for profile generation and verified iOS/WebKit scheduling."""

WEBKIT_NATIVE_CAPABILITY = "webkit_full_native_v1"
WEBKIT_HOST_LIMITATION = (
    "iOS/WebKit requires verified native media on Linux or macOS. "
    "WebKit on Windows is disabled; use Android/Chromium for mobile sessions."
)


def webkit_host_allowed(system: str) -> bool:
    return system.lower() in {"linux", "macos", "darwin"}


def verified_webkit_worker(manifest: dict | None) -> bool:
    return bool(
        manifest
        and webkit_host_allowed(manifest.get("operating_system", ""))
        and any(
            runtime.get("backend") == "playwright"
            and runtime.get("engine") == "webkit"
            and runtime.get("installed")
            and runtime.get("smoke_test") == "passed"
            and WEBKIT_NATIVE_CAPABILITY in runtime.get("parameters", [])
            for runtime in manifest.get("runtimes", [])
        )
    )
