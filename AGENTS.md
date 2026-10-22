# AGENTS.md

Conventions for agents and humans working in this repository.

## What this is

A static pipeline plus viewer charting the land ceded by **Native nations of the United
States**, sourcing the Royce schedule as digitised by the U.S. Forest Service, and exporting
SVGs for Wikimedia Commons. `site/` is deployed to GitHub Pages by
`.github/workflows/pages.yml`.

Scope is deliberate: only Native nations' cession records. No world polities, no colonial
empires, no modern states. If a proposed addition is not a Native nation's cession, it does not
belong in the dataset.

## Commands

```powershell
py pipeline\fetch_tribal_cessions.py                # fetch Royce/USFS cessions
py pipeline\fetch_us_states.py                      # fetch Natural Earth state outlines
py pipeline\build_site_data.py --report             # 415 nations, 717 polygons
py pipeline\build_terrain.py --all                  # relief sheets for every nation
py pipeline\export_svg.py --top 5                   # Commons-ready SVGs in dist/svg/
py -m http.server 8000 --directory site             # preview the site
```

## Checks to run before committing

There is no linter or test suite. Run all of these; they are fast because the pipeline is
standard library only.

```powershell
py -m py_compile pipeline\build_site_data.py pipeline\fetch_tribal_cessions.py pipeline\fetch_us_states.py pipeline\build_terrain.py pipeline\export_svg.py
node --check site\app.js
py pipeline\build_site_data.py --out <tmp> --report --pretty
py pipeline\export_svg.py --data <tmp> --out <tmp-svg> --top 3
```

Then confirm every generated SVG parses as XML:

```powershell
Get-ChildItem <tmp-svg>\*.svg | ForEach-Object { [void][xml](Get-Content $_.FullName -Raw) }
```

## Invariants — do not break these

1. **Scope.** Cessions by Native nations of the United States only, 1784–1893. Global polities,
   empires and modern states are out of scope even when a source offers them.
2. **License chains.** Upstream data must permit commercial use and derivatives. Public domain →
   CC BY-SA 4.0 output is fine. NC or ND upstream data cannot ship, and cannot be uploaded to
   Commons. See `docs/commons-upload.md`.
3. **Attribution travels with the data.** `meta.attribution` from `build_site_data.py` must
   appear in the site footer and in every exported SVG. If you add a source, add it to
   `ATTRIBUTION.md` and to the meta block.
4. **No heavy dependencies.** The pipeline is standard library only and must stay that way:
   no geopandas, shapely, pyproj or GDAL. Areas come from a spherical-excess computation;
   simplification is a hand-rolled Douglas-Peucker pass.
5. **No new runtime dependencies in `site/`.** No CDNs, no npm, no map tiles. The viewer is
   hand-rolled SVG so it works offline and inside the Pages artifact.
6. **Cessions are cumulative losses, not extents.** Never treat a cession entry as "land held".
   A cession jointly made by several nations is credited in full to each; per-nation totals
   therefore do not partition the national total, and the aggregate is not a sum of them.
7. **Cession geometry is shared.** All cession polygons live in one geometry bucket
   (`royce-cessions`) referenced by each series entry's `g` field. Do not duplicate them per
   nation.
8. **Context layers are public domain.** State outlines come from Natural Earth (CC0) and
   relief comes from SRTM (NASA, public domain). Do not substitute a source with noncommercial
   terms.
9. **Relief is decoration, not evidence.** The shaded relief and contour lines are context for
   the cession boundary. Never let them imply a surveyed border: the cession line is the data.

## Data model

`site/data/polities.json` (index + `meta`), `site/data/series.json` (`key` →
`[{from, to, area, type, i, g, s}]`, where `s` lists the states the land now lies in),
`site/data/geom/<shard>.json` (`geometryKey` → geometry array indexed by `i`, plus
`us-states` for the state outlines), `site/data/terrain.json` and `site/data/terrain/*.png`
for the relief sheets. Cession keys are `royce-<tribe>`, plus the aggregate
`royce-all`.

## Conventions

- Python 3.13, standard library, `from __future__ import annotations`, `argparse` CLIs that
  print a `[stage]` prefixed log line per action.
- Site code is a single ES module, no framework, no build step.
- No comments in code unless the reasoning is genuinely non-obvious.
