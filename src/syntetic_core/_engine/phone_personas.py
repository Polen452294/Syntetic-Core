"""Coherent phone models and OS/orientation/browser-area presets.

CSS geometry starts with Playwright's catalogue; full screens are checked against
manufacturers. Browser-area modes simulate toolbar space, not native browser UI.
"""

import random
import re
from typing import Literal, NamedTuple

from syntetic_core._engine.personas import (
    BrowserPersona,
    ChromiumIdentity,
    DeviceConfig,
    PhoneIdentity,
)

PhoneFamily = Literal["android", "ios"]
Orientation = Literal["portrait", "landscape"]
BrowserArea = Literal["expanded", "compact", "minimal"]


class PhoneModel(NamedTuple):
    family: PhoneFamily
    model: str
    width: int
    height: int
    viewport_height: int
    dpr: float
    versions: tuple[str, ...]
    form_factor: Literal["phone", "tablet", "foldable"] = "phone"


ANDROID_13 = ("13.0.0", "14.0.0", "15.0.0", "16.0.0")
ANDROID_14 = ANDROID_13[1:]
IOS_18 = ("18.6", "18.7", "26.0", "26.1", "26.2", "26.3")
IOS_26 = IOS_18[2:]

# Full screen dimensions, not Playwright's toolbar-reduced viewport. Versions
# respect launch OS and official update ceilings; this is not a latest-OS list.
PHONE_MODELS = (
    PhoneModel("android", "Pixel 5", 393, 851, 727, 2.75, ANDROID_13[:2]),
    PhoneModel("android", "Pixel 5a", 393, 873, 749, 2.75, ANDROID_13[:2]),
    PhoneModel("android", "Pixel 6", 412, 915, 839, 2.625, ANDROID_13),
    PhoneModel("android", "Pixel 6 Pro", 412, 892, 816, 3.5, ANDROID_13),
    PhoneModel("android", "Pixel 6a", 412, 915, 839, 2.625, ANDROID_13),
    PhoneModel("android", "Pixel 7", 412, 915, 839, 2.625, ANDROID_13),
    PhoneModel("android", "Pixel 7 Pro", 412, 892, 816, 3.5, ANDROID_13),
    PhoneModel("android", "Pixel 7a", 412, 915, 839, 2.625, ANDROID_13),
    PhoneModel("android", "Pixel 8", 412, 915, 839, 2.625, ANDROID_14),
    PhoneModel("android", "Pixel 8 Pro", 448, 998, 921, 3, ANDROID_14),
    PhoneModel("android", "Pixel 8a", 412, 915, 839, 2.625, ANDROID_14),
    PhoneModel("android", "Pixel 9", 360, 808, 732, 3, ANDROID_14),
    PhoneModel("android", "Pixel 9a", 360, 808, 732, 3, ("15.0.0", "16.0.0")),
    PhoneModel("android", "Pixel 9 Pro", 427, 952, 876, 3, ANDROID_14),
    PhoneModel("android", "Pixel 9 Pro XL", 448, 998, 921, 3, ANDROID_14),
    PhoneModel("android", "Pixel 10", 360, 808, 732, 3, ("16.0.0",)),
    PhoneModel("android", "Pixel 10 Pro", 427, 952, 876, 3, ("16.0.0",)),
    PhoneModel("android", "Pixel 10 Pro XL", 448, 998, 921, 3, ("16.0.0",)),
    PhoneModel("android", "SM-S921U", 360, 780, 704, 3, ANDROID_14),
    PhoneModel("android", "SM-A556B", 480, 1040, 939, 2.25, ANDROID_14),
    PhoneModel("ios", "iPhone 11", 414, 896, 715, 2, IOS_18),
    PhoneModel("ios", "iPhone 11 Pro", 375, 812, 635, 3, IOS_18),
    PhoneModel("ios", "iPhone 11 Pro Max", 414, 896, 715, 3, IOS_18),
    PhoneModel("ios", "iPhone SE (2nd gen)", 375, 667, 548, 2, IOS_18),
    PhoneModel("ios", "iPhone 12 mini", 375, 812, 629, 3, IOS_18),
    PhoneModel("ios", "iPhone 12", 390, 844, 664, 3, IOS_18),
    PhoneModel("ios", "iPhone 12 Pro", 390, 844, 664, 3, IOS_18),
    PhoneModel("ios", "iPhone 12 Pro Max", 428, 926, 746, 3, IOS_18),
    PhoneModel("ios", "iPhone 13 mini", 375, 812, 629, 3, IOS_18),
    PhoneModel("ios", "iPhone 13", 390, 844, 664, 3, IOS_18),
    PhoneModel("ios", "iPhone 13 Pro", 390, 844, 664, 3, IOS_18),
    PhoneModel("ios", "iPhone 13 Pro Max", 428, 926, 746, 3, IOS_18),
    PhoneModel("ios", "iPhone SE (3rd gen)", 375, 667, 548, 2, IOS_18),
    PhoneModel("ios", "iPhone 14", 390, 844, 664, 3, IOS_18),
    PhoneModel("ios", "iPhone 14 Plus", 428, 926, 746, 3, IOS_18),
    PhoneModel("ios", "iPhone 14 Pro", 393, 852, 660, 3, IOS_18),
    PhoneModel("ios", "iPhone 14 Pro Max", 430, 932, 740, 3, IOS_18),
    PhoneModel("ios", "iPhone 15", 393, 852, 659, 3, IOS_18),
    PhoneModel("ios", "iPhone 15 Plus", 430, 932, 739, 3, IOS_18),
    PhoneModel("ios", "iPhone 15 Pro", 393, 852, 659, 3, IOS_18),
    PhoneModel("ios", "iPhone 15 Pro Max", 430, 932, 739, 3, IOS_18),
    PhoneModel("ios", "iPhone 16", 393, 852, 659, 3, IOS_18),
    PhoneModel("ios", "iPhone 16 Plus", 430, 932, 739, 3, IOS_18),
    PhoneModel("ios", "iPhone 16 Pro", 402, 874, 681, 3, IOS_18),
    PhoneModel("ios", "iPhone 16 Pro Max", 440, 956, 763, 3, IOS_18),
    PhoneModel("ios", "iPhone 16e", 390, 844, 651, 3, IOS_18),
    PhoneModel("ios", "iPhone 17", 402, 874, 681, 3, IOS_26),
    PhoneModel("ios", "iPhone Air", 420, 912, 719, 3, IOS_26),
    PhoneModel("ios", "iPhone 17 Pro", 402, 874, 681, 3, IOS_26),
    PhoneModel("ios", "iPhone 17 Pro Max", 440, 956, 763, 3, IOS_26),
    PhoneModel("ios", "iPhone 17e", 390, 844, 651, 3, ("26.3",)),
    PhoneModel("ios", "iPad Pro 11 (M1)", 834, 1194, 1090, 2, IOS_18, "tablet"),
    PhoneModel("ios", "iPad Pro 12.9 (M1)", 1024, 1366, 1262, 2, IOS_18, "tablet"),
    PhoneModel("ios", "iPad Air 5", 820, 1180, 1076, 2, IOS_18, "tablet"),
    PhoneModel("ios", "iPad mini 6", 744, 1133, 1029, 2, IOS_18, "tablet"),
    PhoneModel("android", "SM-F956U", 928, 1080, 1004, 2, ANDROID_14, "foldable"),
    PhoneModel("android", "SM-F966U", 984, 1092, 1016, 2, ("16.0.0",), "foldable"),
)


class PhonePreset(NamedTuple):
    key: str
    phone: PhoneModel
    os_version: str
    orientation: Orientation
    browser_area: BrowserArea
    viewport_width: int
    viewport_height: int

    def device(self) -> DeviceConfig:
        width, height = self.phone.width, self.phone.height
        if self.orientation == "landscape":
            width, height = height, width
        return DeviceConfig(
            source="custom",
            mobile=True,
            touch=True,
            screen={"width": width, "height": height},
            viewport={"width": self.viewport_width, "height": self.viewport_height},
            device_scale_factor=self.phone.dpr,
        )


def _presets(phone: PhoneModel) -> tuple[PhonePreset, ...]:
    slug = re.sub(r"[^a-z0-9]+", "-", phone.model.lower()).strip("-")
    result = []
    # CSS-space reservations scale with Android display density. iOS also leaves
    # side space for notches/Dynamic Island when in landscape orientation.
    scale = phone.width / 360 if phone.family == "android" and phone.form_factor == "phone" else 1
    areas: tuple[BrowserArea, ...] = ("expanded", "compact", "minimal")
    orientations: tuple[Orientation, ...] = ("portrait", "landscape")
    for version in phone.versions:
        for orientation in orientations:
            for area, offset in zip(areas, (0, 24, 48), strict=True):
                if orientation == "portrait":
                    width = phone.width
                    height = min(
                        phone.height - round(28 * scale),
                        phone.viewport_height + round(offset * scale),
                    )
                else:
                    inset = (
                        44
                        if (
                            phone.family == "ios"
                            and phone.form_factor == "phone"
                            and phone.height > 667
                        )
                        else 0
                    )
                    width = phone.height - inset * 2
                    height = phone.width - round((96 - offset) * scale)
                result.append(
                    PhonePreset(
                        f"{slug}-os{version}-{orientation}-{area}",
                        phone,
                        version,
                        orientation,
                        area,
                        width,
                        height,
                    )
                )
    return tuple(result)


PRESETS_BY_MODEL = {phone.model: _presets(phone) for phone in PHONE_MODELS}
PHONE_PRESETS = tuple(preset for presets in PRESETS_BY_MODEL.values() for preset in presets)


def randomize_phone(
    template: BrowserPersona,
    family: PhoneFamily,
    rng: random.Random,
    *,
    allow_tablets: bool = False,
    allow_foldables: bool = False,
) -> BrowserPersona:
    persona = template.model_copy(deep=True)
    # More OS versions must not increase a model's probability. Family weights
    # are selected by the caller, independently of the size of this catalogue.
    models = [
        phone
        for phone in PHONE_MODELS
        if phone.family == family
        and (
            phone.form_factor == "phone"
            or (phone.form_factor == "tablet" and allow_tablets)
            or (phone.form_factor == "foldable" and allow_foldables)
        )
    ]
    model = rng.choice(models)
    orientation = "landscape" if rng.random() < 0.1 else "portrait"
    preset = rng.choice([p for p in PRESETS_BY_MODEL[model.model] if p.orientation == orientation])
    persona.runtime.backend = "playwright"
    persona.native_audio = None
    persona.native_desktop = None
    persona.native_media = None
    persona.emulation = None
    persona.coherence = None
    persona.runtime.channel = None
    persona.runtime.browser_version = None
    persona.runtime.target_os = family
    persona.runtime.fonts = persona.runtime.webgl = None
    persona.runtime.pin_cpu_cores = False
    persona.browser_engine = "chromium" if family == "android" else "webkit"
    persona.device = preset.device()
    persona.phone = PhoneIdentity(
        family=family,
        form_factor=model.form_factor,
        model=model.model,
        os_version=preset.os_version,
        orientation=preset.orientation,
        preset_id=preset.key,
        # Browser-visible count, not CPU performance emulation. Every Android
        # model in this catalogue has at least eight physical cores.
        hardware_concurrency=8 if family == "android" else None,
    )
    persona.chromium = (
        ChromiumIdentity(platform_version=persona.phone.os_version) if family == "android" else None
    )
    persona.runtime.webrtc = "proxy_only"
    if persona.behavior.enabled:
        pace = rng.choice((0.85, 1.0, 1.2, 1.45))
        persona.behavior.pause_min_ms = round(rng.randint(180, 350) * pace)
        persona.behavior.pause_max_ms = round(rng.randint(650, 1200) * pace)
        persona.behavior.key_min_ms = round(rng.randint(65, 110) * pace)
        persona.behavior.key_max_ms = round(rng.randint(170, 290) * pace)
        persona.behavior.scroll_steps = rng.randint(3, 8)
    return persona
