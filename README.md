# Nations' Land Over Time

Interactive visualizations of how much land each nation held **after European contact**, with
standalone SVG exports intended for upload to Wikimedia Commons.

Part of **The Indigenous Spatial Analytics Project**.

- **Live site:** https://getanirao.github.io/The-Indigenous-Spatial-Analytics-Project/
- **Data:** [Cliopatria](https://doi.org/10.5281/zenodo.20274630) (Seshat Global History Databank), CC BY 4.0
- **This repo's output:** CC BY-SA 4.0 (see [LICENSE](LICENSE))

## The window

The build defaults to **1492–present**. Records that overlap the window are *clamped*, not
dropped, so a nation recorded as 1325–1521 still appears for 1492–1521. Two consequences worth
stating plainly:

- **1492 is a European framing.** Contact dates differ by region — Australia 1770, Aotearoa
  1769, much of Africa and Asia later still. Narrow the window per region (`--min-year 1770`)
  instead of treating one date as universal.
- The pre-contact portion of each series is deliberately out of scope for now.

## What it does

1. **Fetch extents** — `pipeline/fetch_cliopatria.py` pulls the Cliopatria release from Zenodo via
   the Zenodo API (no hardcoded filenames) and extracts `cliopatria.geojson` to `data/raw/`.
2. **Fetch cessions** — `pipeline/fetch_tribal_cessions.py` queries the US Forest Service
   "Tribal Ceded Lands" ArcGIS service, joins the polygons to Royce's 1899 schedule, and writes
   `data/raw/tribal_cessions.geojson`.
3. **Build** — `pipeline/build_site_data.py` turns both sources into one small static dataset:
   area-over-time series per nation, plus simplified geometry split into shards for lazy
   loading. Pure standard library — no GDAL, no geopandas.
4. **Serve** — `site/` is a dependency-free static viewer (hand-rolled SVG, no CDNs, no map
   tiles) deployed to GitHub Pages by Actions on every push to `main`.
5. **Export** — `pipeline/export_svg.py` renders standalone, script-free SVG charts and maps
   suitable for Wikimedia Commons, with license and source metadata embedded.

## Quick start

```powershell
py pipeline\fetch_cliopatria.py          # ~300 MB download, cached in data/raw/
py pipeline\fetch_tribal_cessions.py     # ~6 MB, 717 US cession polygons
py pipeline\build_site_data.py          # writes site/data/, default window 1492+
py pipeline\build_site_data.py --no-cessions                     # extents only
py pipeline\build_site_data.py --min-year 1770 --max-year 1970   # a narrower lens
py -m http.server 8000 --directory site # open http://localhost:8000
```

Export a Commons-ready SVG for one nation:

```powershell
py pipeline\export_svg.py --key royce-chippewa --out dist\svg
py pipeline\export_svg.py --top 25 --out dist\svg
```

## Data model produced by the build step

| File | Contents |
| --- | --- |
| `site/data/polities.json` | Index: key, name, `kind` (`extent`/`cession`), `source`, year span, peak/total area, shard id |
| `site/data/series.json` | `{key: [{from, to, area, type, i, g}]}` — one entry per source record |
| `site/data/geom/<shard>.json` | `{geometryKey: [<GeoJSON geometry>, ...]}`, addressed by `g` + `i` above |

Extent keys are derived from Wikidata → Seshat ID → slugified name, so the same name across
periods collapses into one series. Cession keys are `royce-<tribe>`; all 717 cession polygons
share one geometry bucket (`royce-cessions`) rather than being duplicated per nation.

Cession series are **cumulative**: the viewer sums cessions by year rather than reading an
"area at year", because a cession records a loss, not a holding.

## Scope and known limitations

- **Coverage is the hard limit.** Cliopatria is a deep-time dataset: post-1492 it thins out for
  Indigenous nations. The cession layer covers only the United States, 1784–1894.
- **Cessions are losses, not holdings.** A cession series shows cumulative land *ceded*, which
  is not the same as land still held. Computing remaining territory needs an initial extent
  that neither source provides.
- **Cession geometry is an interpretation.** Royce's 1899 schedule notes that boundaries were
  often described loosely, and some entries describe the tract *reserved* rather than ceded.
  Treat totals as approximate; do not present them as surveyed acreage.
- **Shared cessions are credited in full.** A cession made jointly by several nations is
  attributed to each of them, so per-nation totals do not add up to the national total.
- **Metric.** "Land" is the area of the recorded polygons, in km², computed geodesically.
  Records are snapshots at varying timesteps, so series are step functions.
- **Overlap.** Nations can overlap in time (vassalage, composite/`RELATION` entries). Areas
  are per-entity and are **not** summed into a world total.
- **Antimeridian.** The map uses a plain equirectangular projection; entities crossing ±180°
  can render with spurious horizontal seams.

## Licensing and attribution

Source data is CC BY 4.0, which permits the CC BY-SA 4.0 license applied to this repo's
visualizations and derived data. Attribution is mandatory — see [ATTRIBUTION.md](ATTRIBUTION.md)
and the notes in [docs/commons-upload.md](docs/commons-upload.md) before uploading anything.

## Contributing

See [AGENTS.md](AGENTS.md) for conventions and the commands to run before committing.

## Roadmap

- Canada: historic treaties and reserve boundaries (Open Government Licence – Canada).
- Remaining territory over time, not just cumulative cession (requires pre-contact extents).
- Per-region contact windows instead of a single 1492 cutoff.
- Animated GIF/WebP exports in addition to SVG.
