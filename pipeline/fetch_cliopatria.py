#!/usr/bin/env python3
"""Download the Cliopatria dataset from Zenodo and extract cliopatria.geojson.

Files are resolved through the Zenodo API rather than a hardcoded archive name, so the
script survives upstream re-releases. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_RECORD = "20274630"  # Cliopatria v0.2.0
API = "https://zenodo.org/api/records/{record}"
USER_AGENT = (
    "indigenous-spatial-analytics/fetch-cliopatria "
    "(+https://github.com/getanirao/The-Indigenous-Spatial-Analytics-Project)"
)
GEOJSON_SUFFIX = ".geojson"
CANONICAL_NAME = "cliopatria.geojson"


def log(message: str) -> None:
    print(f"[fetch] {message}", flush=True)


def fetch_record(record: str) -> dict:
    url = API.format(record=record)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Zenodo API returned HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach Zenodo at {url}: {exc.reason}") from exc


def pick_file(files: list[dict]) -> dict:
    """Prefer a bare .geojson, else the archive that contains one."""
    geojson = [f for f in files if f["key"].lower().endswith(GEOJSON_SUFFIX)]
    if geojson:
        return geojson[0]
    archives = [f for f in files if f["key"].lower().endswith(".zip")]
    if archives:
        return archives[0]
    available = ", ".join(f["key"] for f in files) or "(none)"
    raise SystemExit(f"No .geojson or .zip in this record. Found: {available}")


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp, dest.open("wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                pct = 100.0 * done / total
                print(
                    f"\r  {done / 1e6:,.1f}/{total / 1e6:,.1f} MB ({pct:5.1f}%)",
                    end="",
                    flush=True,
                )
            else:
                print(f"\r  {done / 1e6:,.1f} MB", end="", flush=True)
    print(flush=True)
    return dest


def extract_geojson(archive: Path, raw_dir: Path, depth: int = 0) -> Path:
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        members = [m for m in names if m.lower().endswith(GEOJSON_SUFFIX)]
        if not members:
            members = [m for m in names if m.lower().endswith(".json")]
        if members:
            members.sort(key=lambda m: (Path(m).name.lower() != CANONICAL_NAME, len(m)))
            member = members[0]
            out = raw_dir / CANONICAL_NAME
            log(f"extracting {member} -> {out}")
            with zf.open(member) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            return out
        nested = [m for m in names if m.lower().endswith(".zip")]
        if not nested:
            raise SystemExit(f"{archive.name} contains no .geojson, .json or .zip member")
        if depth >= 2:
            raise SystemExit(f"{archive.name}: too many nested archives ({nested[0]})")
        nested.sort(key=lambda m: (GEOJSON_SUFFIX not in Path(m).name.lower(), -len(m)))
        member = nested[0]
        inner = raw_dir / f"{Path(member).stem}.nested.zip"
        log(f"descending into {member}")
        with zf.open(member) as src, inner.open("wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
    try:
        return extract_geojson(inner, raw_dir, depth + 1)
    finally:
        inner.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", default=DEFAULT_RECORD, help="Zenodo record id")
    parser.add_argument("--raw-dir", default="data/raw", help="destination directory")
    parser.add_argument("--force", action="store_true", help="re-download if present")
    parser.add_argument("--dry-run", action="store_true", help="print URLs, download nothing")
    args = parser.parse_args(argv)

    raw_dir = Path(args.raw_dir)
    meta = fetch_record(args.record)
    md = meta.get("metadata", {})
    log(f"record {args.record}: {md.get('title', 'unknown title')}")
    log(f"version {md.get('version', '?')}  license {md.get('license', {}).get('id', '?')}")

    target = pick_file(meta.get("files", []))
    url = target["links"]["self"]
    extracted = raw_dir / CANONICAL_NAME

    if extracted.exists() and not args.force:
        log(f"{extracted} already present ({extracted.stat().st_size / 1e6:,.1f} MB); use --force")
        return 0

    log(f"selected {target['key']} ({target.get('size', 0) / 1e6:,.1f} MB)")
    log(f"url {url}")
    if args.dry_run:
        return 0

    archive = download(url, raw_dir / Path(target["key"]).name)
    if archive.suffix.lower() == ".zip":
        result = extract_geojson(archive, raw_dir)
    else:
        result = extracted
        if archive != extracted:
            shutil.move(str(archive), str(extracted))
    log(f"ready: {result} ({result.stat().st_size / 1e6:,.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
