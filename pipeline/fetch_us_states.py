#!/usr/bin/env python3
"""Download US state boundaries for the map backdrop.

Natural Earth is public domain (CC0): https://www.naturalearthdata.com/about/terms-of-use/
The 50m admin-1 layer is small enough to keep in the repository's data directory and coarse
enough to sit under the cession polygons without competing with them.

Writes data/raw/us_states.geojson: one feature per state, with name, code and geometry.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
    "ne_50m_admin_1_states_provinces.geojson"
)
KEEP_TYPES = ("State", "Federal District")


def log(message: str) -> None:
    print(f"[states] {message}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/raw/us_states.geojson")
    parser.add_argument("--url", default=URL)
    parser.add_argument("--force", action="store_true", help="re-download even if the file exists")
    parser.add_argument("--dry-run", action="store_true", help="print the source and exit")
    args = parser.parse_args(argv)

    if args.dry_run:
        log(f"source: {args.url}")
        return 0

    out_path = Path(args.out)
    if out_path.exists() and not args.force:
        log(f"{out_path} already exists (use --force to refetch)")
        return 0

    log(f"downloading {args.url}")
    request = urllib.request.Request(args.url, headers={"User-Agent": "isap/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))

    features = []
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        if properties.get("adm0_a3") != "USA":
            continue
        if properties.get("type") not in KEEP_TYPES:
            continue
        if not feature.get("geometry"):
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": properties.get("name"),
                    "code": properties.get("postal"),
                    "long": properties.get("name_en") or properties.get("name"),
                },
                "geometry": feature["geometry"],
            }
        )

    if not features:
        raise SystemExit("no US states found in the downloaded layer")

    features.sort(key=lambda feature: feature["properties"]["name"] or "")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh, ensure_ascii=False)
    log(f"wrote {out_path} ({len(features)} states and districts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
