#!/usr/bin/env python3
"""Download major lake outlines for the relief sheets.

Natural Earth is public domain (CC0): https://www.naturalearthdata.com/about/terms-of-use/
Lake surfaces are positive elevations in the SRTM tiles, so without this mask the Great Lakes
and other large lakes read as land. The 50m layer is coarse enough to sit under the cession
polygons without competing with them.

Writes data/raw/us_lakes.geojson: one feature per lake, clipped to the North American window,
with name and polygon rings only.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
    "ne_50m_lakes.geojson"
)
WINDOW = (-170.0, 15.0, -60.0, 72.0)


def log(message: str) -> None:
    print(f"[lakes] {message}", flush=True)


def ring_bounds(ring: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def intersects(bounds: tuple[float, float, float, float]) -> bool:
    return not (
        bounds[2] < WINDOW[0]
        or bounds[0] > WINDOW[2]
        or bounds[3] < WINDOW[1]
        or bounds[1] > WINDOW[3]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/raw/us_lakes.geojson")
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
        geometry = feature.get("geometry")
        if not geometry:
            continue
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        kept = [polygon for polygon in polygons if polygon and intersects(ring_bounds(polygon[0]))]
        if not kept:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {"name": (feature.get("properties") or {}).get("name")},
                "geometry": {"type": "MultiPolygon", "coordinates": kept},
            }
        )

    if not features:
        raise SystemExit("no lakes found in the downloaded layer")

    features.sort(key=lambda feature: feature["properties"]["name"] or "")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh, ensure_ascii=False)
    log(f"wrote {out_path} ({len(features)} lakes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
