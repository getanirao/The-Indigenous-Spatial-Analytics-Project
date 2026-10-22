# Uploading to Wikimedia Commons

Commons has hard rules that decide whether a file can stay up. Getting these wrong gets the
upload deleted, so work through this checklist per file rather than in bulk.

## 1. License eligibility

Commons only accepts licenses that permit **commercial use and derivative works**. Two
consequences for this project:

- **CC BY-SA 4.0 is fine** for our figures. It is the license declared in [LICENSE](../LICENSE).
- **CC BY-NC anything is not.** If a future dataset is NonCommercial — several Indigenous
  mapping projects are — its output **cannot** go on Commons, no matter how open it looks.
  Check `ATTRIBUTION.md` and the upstream record before you render.

Our figures are adaptations of CC BY 4.0 material redistributed under CC BY-SA 4.0. That is
allowed, and the share-alike term does **not** prevent the upload. It does mean you cannot
relicense the figure as CC BY 4.0 or public domain to "simplify" attribution.

Cession figures are built on U.S. Government works (Royce 1899; the Forest Service digitisation
with Claudio Saunt), which are public domain in the United States. They are freely uploadable,
but credit them anyway — the digitisation is someone's labour, and the 1899 schedule carries its
own interpretive choices.

## 2. Attribution is a condition, not a courtesy

Use the credit block from [ATTRIBUTION.md](../ATTRIBUTION.md). Both layers are required: the
upstream dataset authors *and* the adaptation. A figure missing the Cliopatria citation is a
license violation, not a style issue.

## 3. File naming

```
<Polity> land area over time <from>-<to>.svg
<Polity> territory <year>.svg
<Nation> cumulative land ceded.svg
<Nation> ceded by <year>.svg
```

Prefer ASCII and the nation's common English name. Avoid "final", "v2", "corrected" — upload a
new revision instead so the history stays intact.

## 4. Information template

```
{{Information
|description={{en|1=Recorded land area of the [[:en:Aztec Empire|Aztec Empire]] from 1492 to
1521, from the Cliopatria geospatial dataset. Values are snapshots at uneven intervals, not
annual measurements.}}
{{fr|1=Superficie enregistrée de l'Empire aztèque de 1492 à 1521...}}
|date=2026-10-22
|source={{own}}, derived from Bennett, Mutch & Chalstrey (2024), Cliopatria,
https://doi.org/10.5281/zenodo.20274630 (CC BY 4.0)
|author=The Indigenous Spatial Analytics Project
|other_versions=
}}
```

Then add the license tag and the upstream attribution:

```
== {{int:license-header}} ==
{{self|cc-by-sa-4.0}}
{{Attribution-Cliopatria}}
```

For a cession figure from US Government sources:

```
|source={{own}}, derived from Royce, C. C., Indian Land Cessions in the United States (1899),
digitised by the U.S. Forest Service and Claudio Saunt (public domain)
```

```
== {{int:license-header}} ==
{{self|cc-by-sa-4.0}}
{{PD-USGov-USDA-FS}}
{{Attribution-Royce-Cessions}}
```

`{{Attribution-Cliopatria}}` and `{{Attribution-Royce-Cessions}}` will not exist yet — either
create those templates with the credit block, or paste the plain-text attribution into the file
page. Prefer templates: they keep every figure consistent when a dataset version changes.

## 5. Categories

Verify exact names on Commons before saving; category names drift.

- `[[Category:Cliopatria]]` (create if absent, as a subcategory of historical atlases)
- `[[Category:Historical maps of the world]]`
- `[[Category:Area charts]]`
- `[[Category:Maps of the Indian land cessions]]`
- `[[Category:Land cessions by the United States]]`
- A region or nation category, e.g. `[[Category:Maps of the Aztec Empire]]`

## 6. Technical requirements

- **Text must be real text, not outlines.** Our exporter emits `<text>` elements, so
  [SVG Translate](https://commons.wikimedia.org/wiki/Commons:SVG_Translate) can localise labels.
  Never convert to paths.
- **No scripts, no external references.** Our SVGs are self-contained; do not add JavaScript to
  animate them on Commons.
- **Embedded `<metadata>` is permitted** and already carries source, version, DOI and license.
- **State the limitations in the description.** Cliopatria polygons are historian-drawn
  approximations of contested sovereignty, and Royce's cession boundaries were never surveyed.
  Say so: a chart that reads like a survey is misleading. For cessions, note that the areas are
  computed from digitised polygons rather than surveyed acreage, and that a cession shared by
  several nations is credited in full to each.
- **Watch file size.** Keep under ~10 MB; drop `--tolerance` to 0.3 for world-scale maps, and
  keep `--cession-tolerance` small or small cessions collapse to nothing.

## 7. Not suitable for Commons

- Interactive or JavaScript-driven pages — those belong on the GitHub Pages site, which Commons
  can link to from the file page (`|other_versions=` or the description).
- Anything aggregating overlapping nations into a single "world total" without a stated
  overlap policy.
- Anything built on NC-licensed Indigenous datasets. Publish those on the site with the
  upstream terms instead.
