# Native Land Cessions

An interactive atlas of the land ceded by Native nations of the United States, nation by
nation, with standalone SVG exports intended for upload to Wikimedia Commons.

Part of **The Indigenous Spatial Analytics Project**.

- **Live site:** https://getanirao.github.io/The-Indigenous-Spatial-Analytics-Project/
- **Data:** Royce, *Indian Land Cessions in the United States* (1899), digitised by the U.S.
  Forest Service with Claudio Saunt (public domain)
- **This repo's output:** CC BY-SA 4.0 (see [LICENSE](LICENSE))

## Scope

The atlas covers **only Native nations of the United States and the land they ceded**, drawn
from the Royce schedule as digitised by the Forest Service.

- 415 nations, 717 cession polygons, 2,198 nation-cession records
- Years 1784–1893, the span of the schedule itself
- No world polities, no colonial empires, no modern states: if a record is not a Native
   nation's cession, it does not belong here

A cession signed by several nations is credited in full to each signatory, so per-nation
totals overlap and never partition the national total.

## What it does

1. **Fetch** — `pipeline/fetch_tribal_cessions.py` queries the US Forest Service "Tribal Ceded
   Lands" ArcGIS service, joins the polygons to Royce's 1899 schedule, and writes
   `data/raw/tribal_cessions.geojson`. `pipeline/fetch_us_states.py` pulls Natural Earth
   (public domain) state outlines for map context, and `pipeline/fetch_us_lakes.py` pulls
   lake outlines so large lakes render as water.
2. **Build** — `pipeline/build_site_data.py` turns that into one small static dataset:
   cumulative-cession series per nation, plus simplified geometry in a single shared bucket.
   Pure standard library — no GDAL, no geopandas.
3. **Relief** — `pipeline/build_terrain.py` renders one continuous topographic sheet for each
   nation: shaded relief and contour lines from SRTM elevation, with Natural Earth lake outlines
   masked back to water, so every map sits on a single base at one zoom and one contour
   interval. The viewer places it under the ceded land, and the SVG exporter embeds it.
4. **Serve** — `site/` is a dependency-free static viewer (hand-rolled SVG, no CDNs, no map
   tiles) deployed to GitHub Pages by Actions on every push to `main`.
5. **Export** — `pipeline/export_svg.py` renders standalone, script-free SVG charts and maps
   suitable for Wikimedia Commons, with license and source metadata embedded.

## Quick start

```powershell
py pipeline\fetch_tribal_cessions.py     # ~6 MB, 717 US cession polygons
py pipeline\fetch_us_states.py           # ~2 MB, 51 state outlines
py pipeline\fetch_us_lakes.py            # ~240 KB, 188 lake outlines
py pipeline\build_site_data.py --report  # writes site/data/
py pipeline\build_terrain.py --all       # topographic sheets for every nation
py -m http.server 8000 --directory site  # open http://localhost:8000
```

Export a Commons-ready SVG for one nation:

```powershell
py pipeline\export_svg.py --key royce-cherokee --out dist\svg
py pipeline\export_svg.py --top 25 --out dist\svg
```

## Data model produced by the build step

| File | Contents |
| --- | --- |
| `site/data/polities.json` | Index: key, name, year span, total ceded area, states touched, shard id, `meta` block |
| `site/data/series.json` | `{key: [{from, to, area, type, i, g, s}]}` — one entry per cession record; `s` lists the states the land now lies in |
| `site/data/geom/<shard>.json` | `{geometryKey: [<GeoJSON geometry>, ...]}`, addressed by `g` + `i` above, plus `us-states` for the state outlines |
| `site/data/terrain.json` | `{key: [{file, lon0, lat0, lon1, lat1, zoom, interval}]}` — the relief sheet for each nation |
| `site/data/terrain/*.png` | One shaded-relief sheet with contour lines per nation |

Keys are `royce-<tribe>`, except the national aggregate `royce-all`. All 717 cession polygons
share one geometry bucket (`royce-cessions`) referenced by each nation's records, so a joint
cession is stored once rather than duplicated per signatory.

Cession series are **cumulative**: the viewer sums cessions up to the selected year. A cession
records a loss, not a holding, so "area over time" means "total ceded by this date".

## Known limitations

- **Cessions are losses, not holdings.** A series shows cumulative land ceded, which is not the
  same as land still held. Remaining territory would need an initial extent that the schedule
  does not provide.
- **Cession geometry is an interpretation.** Royce's 1899 schedule notes that boundaries were
  often described loosely, and some entries describe the tract *reserved* rather than ceded.
  Treat totals as approximate; do not present them as surveyed acreage.
- **Shared cessions are credited in full.** Per-nation totals therefore do not add up to the
  national total, and the aggregate is not a sum of the others.
- **Metric.** "Land" is the area of the recorded polygons, in km², computed geodesically.
- **State context is modern.** The state a ceded tract falls in today is computed by
  intersection with Natural Earth outlines, so it says where the land is now, not which
  jurisdiction held it in 1866.
- **Coverage.** The United States only: Canada and Mexico are out of scope until a comparable
  nation-level dataset is added.

## Licensing and attribution

The underlying schedule and its digitisation are U.S. Government works, public domain in the
United States. This repo's visualizations and derived data are released under CC BY-SA 4.0.
Attribution is mandatory — see [ATTRIBUTION.md](ATTRIBUTION.md) and the notes in
[docs/commons-upload.md](docs/commons-upload.md) before uploading anything.

## Contributing

See [AGENTS.md](AGENTS.md) for conventions and the commands to run before committing.

## Roadmap

- Canada: historic treaties and reserve boundaries (Open Government Licence — Canada).
- Per-year map framing and animated GIF/WebP exports in addition to SVG.
- Remaining territory over time, once a defensible pre-cession extent exists.
