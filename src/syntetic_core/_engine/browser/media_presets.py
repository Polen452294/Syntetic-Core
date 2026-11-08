"""Explicit native Camoufox device sets drawn from its pinned OS catalogues."""

import json
from pathlib import Path
from typing import Any

from syntetic_core._engine.personas import BrowserPersona


def apply_media_preset(config: dict[str, Any], persona: BrowserPersona) -> None:
    preset = persona.native_media
    if preset is None:
        return
    if persona.runtime.backend != "camoufox":
        raise ValueError("Native media presets require Camoufox")
    if preset.devices != "library":
        import camoufox

        catalogue = json.loads(
            (Path(camoufox.__file__).parent / "media-devices.json").read_text(encoding="utf-8")
        )
        os_key = {"windows": "win", "macos": "mac", "linux": "lin"}[
            persona.runtime.target_os or "linux"
        ]
        data = catalogue[os_key]
        card = data["cards"][0]
        microphones = list(card.get("mics", []))[:1]
        speakers = list(card.get("outs", []))[:1]
        # Webcam labels are OS-independent USB model names from the vendor catalogue.
        cameras = [card.get("cam", "Logitech HD Pro Webcam C920")]
        if preset.devices == "conference":
            headset = data["headsets"][0]
            microphones += headset.get("mics", [])[:1]
            speakers += headset.get("outs", [])[:1]
        if preset.devices == "none":
            microphones, speakers, cameras = [], [], []
        config["mediaDevices:enabled"] = True
        for key, label, values in [
            ("micros", "microphone", microphones),
            ("webcams", "webcam", cameras),
            ("speakers", "speaker", speakers),
        ]:
            config["mediaDevices:" + key] = len(values)
            config["mediaDevices:" + label + "Labels"] = values
            config["mediaDevices:" + label + "Groups"] = [
                "device-group-" + str(i) for i in range(len(values))
            ]
    if preset.voices == "none":
        config["voices"] = []
        config["voices:blockIfNotDefined"] = True
    elif preset.voices == "local" and "voices" not in config:
        from camoufox.fingerprints import _generate_random_voice_subset

        voices = _generate_random_voice_subset(
            persona.runtime.target_os or "linux",
            persona.locale,
            seed=int((persona.fingerprint_id or "0")[:8], 16),
        )
        config["voices"] = [v for v in voices if v["isLocalService"]]
        config["voices:blockIfNotDefined"] = True


async def observe_media(page: Any, *, main_world: bool = True) -> dict[str, Any]:
    return await page.evaluate(
        ("mw:" if main_world else "")
        + """async () => {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const voices = await new Promise(resolve => {
            const current = speechSynthesis.getVoices();
            if (current.length) return resolve(current);
            const done = () => resolve(speechSynthesis.getVoices());
            speechSynthesis.addEventListener('voiceschanged', done, {once:true});
            setTimeout(done, 200);
        });
        const permissions = {};
        for (const name of ['camera','microphone']) {
            try { permissions[name]=(await navigator.permissions.query({name})).state; }
            catch { permissions[name]='unavailable'; }
        }
        return {permissions,
                devices: devices.map(d => ({kind:d.kind,label:d.label,group:d.groupId})),
                voices: voices.map(v => ({name:v.name,lang:v.lang,local:v.localService}))};
    }"""
    )
