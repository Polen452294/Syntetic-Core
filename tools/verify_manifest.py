"""Check the frozen destination hashes of the reviewed engine extraction."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(update: bool = False) -> None:
    path = ROOT / "extraction-manifest.json"
    manifest = json.loads(path.read_text("utf-8"))
    for record in manifest["files"]:
        target = (ROOT / record["destination"]).resolve()
        if not target.is_relative_to(ROOT):
            raise ValueError("Manifest path escapes project root")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if update:
            record["destination_sha256"] = digest
        elif digest != record.get("destination_sha256"):
            raise ValueError(f"Extraction destination changed: {record['destination']}")
    if update:
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(manifest['files'])} extracted files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="Record reviewed destination hashes")
    main(parser.parse_args().update)
