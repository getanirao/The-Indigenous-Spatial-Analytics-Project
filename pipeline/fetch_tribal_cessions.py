#!/usr/bin/env python3
"""Fetch the US Forest Service "Tribal Ceded Lands" dataset as joined GeoJSON.

Source: S_USA.TribalCededLands, U.S. Forest Service. It digitises Charles C. Royce's
*Indian Land Cessions in the United States* (1899, U.S. Government work, public domain) and
revises the 2015 digitisation by Claudio Saunt. Polygons carry only a cession map number, so
this script joins them to the schedule table (dates, tribes, citations, links).

Output: data/raw/tribal_cessions.geojson plus a sidecar metadata file.
Standard library only; the ArcGIS REST service is queried directly, no shapefile or .gdb.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SERVICE = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_TribalCessionLands_01/MapServer"
POLYGON_LAYER = "1"
TABLE_LAYER = "2"
PAGE_SIZE = 1000
USER_AGENT = (
    "indigenous-spatial-analytics/fetch-tribal-cessions "
    "(+https://github.com/getanirao/The-Indigenous-Spatial-Analytics-Project)"
)

TABLE_FIELDS = [
    "cessnum", "schdtrb", "presdaytrb", "state", "county", "mapname",
    "cessdate1", "cessdate2", "cessdate3", "cessdate4", "cessdate5",
    "date1link_royce_schedule", "date1link_kappler_treaty",
]

METADATA = {
    "name": "Tribal Ceded Lands (US Forest Service)",
    "description": (
        "Sixty-seven georeferenced maps from Charles C. Royce, Indian Land Cessions in the "
        "United States (Eighteenth Annual Report of the Bureau of American Ethnology, 1899), "
        "digitised by the U.S. Forest Service with Claudio Saunt."
    ),
    "url": SERVICE.rsplit("/MapServer", 1)[0] + "/MapServer",
    "publisher": "U.S. Department of Agriculture, Forest Service",
    "license": "Public domain (U.S. Government work)",
    "note": (
        "Royce's schedule records cessions and reservations from 1784 to 1894. Cession "
        "boundaries were neither contiguous nor well defined; the polygons are one "
        "interpretation of the schedule, not surveyed borders."
    ),
}


def log(message: str) -> None:
    print(f"[cessions] {message}", flush=True)


def get_json(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"ArcGIS returned HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {url}: {exc.reason}") from exc


def fetch_pages(layer: str, params: dict) -> list[dict]:
    features: list[dict] = []
    offset = 0
    while True:
        page = get_json(
            f"{SERVICE}/{layer}/query",
            {**params, "resultOffset": offset, "resultRecordCount": PAGE_SIZE,
             "orderByFields": "objectid"},
        )
        batch = page.get("features", [])
        features.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        log(f"  layer {layer}: {len(features)} features")
    return features


def epoch_ms_to_date(value) -> str | None:
    # datetime.fromtimestamp() raises OSError on Windows for pre-1970 values, and every
    # Royce cession predates 1970, so do the arithmetic explicitly.
    if value in (None, ""):
        return None
    try:
        moment = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=int(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return moment.strftime("%Y-%m-%d")


def split_names(value) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).replace("|", ";").split(";") if part.strip()]


def build_table_index(rows: list[dict]) -> dict[str, dict]:
    index = {}
    for feature in rows:
        attributes = feature.get("attributes", {})
        cessnum = str(attributes.get("cessnum") or "").strip()
        if cessnum:
            index[cessnum] = attributes
    return index


def resolve_date(attributes: dict) -> tuple[str | None, str | None]:
    for field in ("cessdate1", "cessdate2", "cessdate3", "cessdate4", "cessdate5"):
        date = epoch_ms_to_date(attributes.get(field))
        if date:
            return date, field
    return None, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    raw_dir = Path(args.raw_dir)
    out = raw_dir / "tribal_cessions.geojson"
    if out.exists() and not args.force:
        log(f"{out} already present ({out.stat().st_size / 1e6:,.2f} MB); use --force")
        return 0
    if args.dry_run:
        log(f"would query {SERVICE} layers {POLYGON_LAYER} and {TABLE_LAYER}")
        return 0

    log("fetching schedule table")
    table_rows = fetch_pages(TABLE_LAYER, {
        "where": "1=1", "outFields": ",".join(TABLE_FIELDS),
        "returnGeometry": "false", "f": "json",
    })
    table = build_table_index(table_rows)
    log(f"  {len(table)} schedule rows")

    log("fetching cession polygons")
    polygon_rows = fetch_pages(POLYGON_LAYER, {
        "where": "1=1", "outFields": "cessnum", "returnGeometry": "true",
        "outSR": "4326", "f": "geojson",
    })
    log(f"  {len(polygon_rows)} polygons")

    features = []
    undated = 0
    unjoined = 0
    for row in polygon_rows:
        cessnum = str((row.get("properties") or {}).get("cessnum") or "").strip()
        attributes = table.get(cessnum)
        if attributes is None:
            unjoined += 1
            continue
        date, date_field = resolve_date(attributes)
        if date is None:
            undated += 1
            continue
        properties = {
            "cessnum": cessnum,
            "year": int(date[:4]),
            "date": date,
            "dateField": date_field,
            "tribes": split_names(attributes.get("schdtrb")),
            "tribesRaw": attributes.get("schdtrb"),
            "presentDayTribes": split_names(attributes.get("presdaytrb")),
            "state": attributes.get("state"),
            "county": attributes.get("county"),
            "mapName": attributes.get("mapname"),
            "royceUrl": attributes.get("date1link_royce_schedule"),
            "treatyUrl": attributes.get("date1link_kappler_treaty"),
        }
        features.append({"type": "Feature", "properties": properties, "geometry": row.get("geometry")})

    features.sort(key=lambda f: (f["properties"]["year"], f["properties"]["cessnum"]))
    if unjoined:
        log(f"  skipped {unjoined} polygons with no schedule row")
    if undated:
        log(f"  skipped {undated} polygons with no parseable date")
    if not features:
        raise SystemExit(
            "No dated cession polygons were produced; refusing to write an empty dataset. "
            "Check the service response above."
        )

    payload = {
        "type": "FeatureCollection",
        "name": "tribal_cessions",
        "features": features,
        "metadata": {**METADATA, "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    }
    raw_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"wrote {out} ({out.stat().st_size / 1e6:,.2f} MB, {len(features)} features)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
