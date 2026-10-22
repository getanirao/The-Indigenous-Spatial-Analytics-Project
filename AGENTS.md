# AGENTS.md

Conventions for agents and humans working in this repository.

## What this is

A static pipeline plus viewer that charts how much land each nation held after European
contact, sourcing [Cliopatria](https://doi.org/10.5281/zenodo.20274630) (CC BY 4.0), and
exporting SVGs for Wikimedia Commons. `site/` is deployed to GitHub Pages by
`.github/workflows/pages.yml`.

## Commands

```powershell
py pipeline\fetch_cliopatria.py                     # fetch raw data into data/raw/
py pipeline\fetch_tribal_cessions.py                # fetch Royce/USFS cessions
py pipeline\build_site_data.py --report            # default window 1492+
py pipeline\build_site_data.py --min-year -4000    # full deep-time build
py pipeline\export_svg.py --top 5                  # Commons-ready SVGs in dist/svg/
py -m http.server 8000 --directory site            # preview the site
```

## Checks to run before committing

There is no linter or test suite. Run all of these; they are fast because the pipeline is
standard library only.

```powershell
py -m py_compile pipeline\build_site_data.py pipeline\fetch_cliopatria.py pipeline\fetch_tribal_cessions.py pipeline\export_svg.py
node --check site\app.js
py pipeline\build_site_data.py --input <fixture>.geojson --out <tmp> --report --pretty
py pipeline\export_svg.py --data <tmp> --out <tmp-svg> --top 3
```

Then confirm every generated SVG parses as XML:

```powershell
Get-ChildItem <tmp-svg>\*.svg | ForEach-Object { [void][xml](Get-Content $_.FullName -Raw) }
```

## Invariants — do not break these

1. **License chains.** Upstream data must permit commercial use and derivatives. CC BY 4.0 →
   CC BY-SA 4.0 output is fine. NC or ND upstream data cannot ship, and cannot be uploaded to
   Commons. See `docs/commons-upload.md`.
2. **Attribution travels with the data.** `meta.attribution` from `build_site_data.py` must
   appear in the site footer and in every exported SVG. If you add a source, add it to
   `ATTRIBUTION.md` and to the meta block.
3. **No heavy dependencies.** The pipeline is standard library only and must stay that way:
   no geopandas, shapely, pyproj or GDAL. Areas come from Cliopatria's `Area` column with a
   spherical-excess fallback; simplification is a hand-rolled Douglas-Peucker pass.
4. **No new runtime dependencies in `site/`.** No CDNs, no npm, no map tiles. The viewer is
   hand-rolled SVG so it works offline and inside the Pages artifact.
5. **The window is a filter, not an edit.** Never trim `cliopatria.geojson`. Records
   overlapping the window get clamped; the rest are excluded at build time.
6. **Overlaps are never summed.** Per-entity areas stay separate. Reporting a "world total"
   without an explicit overlap policy is a correctness bug, not a feature.
7. **Cessions are cumulative losses, not extents.** Never treat a cession entry as "land held".
   A cession jointly made by several nations is credited in full to each; per-nation totals
   therefore do not partition the national total.
8. **Cession geometry is shared.** All cession polygons live in one geometry bucket
   (`royce-cessions`) referenced by each series entry's `g` field. Do not duplicate them per
   nation.

## Data model

`site/data/polities.json` (index + `meta`), `site/data/series.json` (`key` →
`[{from, to, area, type, i, g}]`), `site/data/geom/<shard>.json` (`geometryKey` → geometry
array indexed by `i`). Each polity carries `kind` (`extent` or `cession`) and `source`.

Extent keys resolve Wikidata → Seshat ID → slugified name, decided per source name so a
nation's records do not fragment across periods. Cession keys are `royce-<tribe>`.

## Conventions

- Python 3.13, standard library, `from __future__ import annotations`, `argparse` CLIs that
  print a `[stage]` prefixed log line per action.
- Site code is a single ES module, no framework, no build step.
- No comments in code unless the reasoning is genuinely non-obvious.
