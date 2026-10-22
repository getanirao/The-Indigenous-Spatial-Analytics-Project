# Attribution

Every visualization, derived dataset, and SVG exported from this repository is a *derived
work* of the sources below. Attribution is a license condition, not a courtesy: include the
block below (or its equivalent) anywhere our output is republished, including Wikimedia
Commons file pages.

## Required credit

> **Extents:** Data: Bennett, J., Mutch, E., & Chalstrey, E. (2024). *Cliopatria — A geospatial
> database of world-wide political entities from 3400BCE to 2024CE.* Seshat: Global History
> Databank. Zenodo. https://doi.org/10.5281/zenodo.20274630 — licensed CC BY 4.0.
>
> **US cessions:** Data: Royce, C. C. (1899). *Indian Land Cessions in the United States.*
> Eighteenth Annual Report of the Bureau of American Ethnology, Smithsonian Institution.
> Digitised and georeferenced by the U.S. Forest Service with Claudio Saunt — public domain
> (U.S. Government work).
>
> **Figure:** *The Indigenous Spatial Analytics Project*,
> https://github.com/getanirao/The-Indigenous-Spatial-Analytics-Project — licensed CC BY-SA 4.0.

## Sources

| Source | Version / date | License | Used for |
| --- | --- | --- | --- |
| [Cliopatria](https://doi.org/10.5281/zenodo.20274630) (Seshat Global History Databank) | v0.2.0, 2026-05-16 | CC BY 4.0 | Polity extents, areas, dates, Wikidata links |
| [Cliopatria paper](https://doi.org/10.1038/s41597-025-04516-9) (*Scientific Data*, 2025) | — | Open access (CC BY 4.0) | Methodology, stated limitations |
| [Tribal Ceded Lands](https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_TribalCessionLands_01/MapServer) (US Forest Service) | 2018 revision | Public domain (US Government work) | US cession polygons, dates, tribes |
| Royce, *Indian Land Cessions in the United States* (1899) | [LOC 13023487](https://www.loc.gov/item/13023487/) | Public domain | Underlying schedule and maps |

## License compatibility

CC BY 4.0 source material may be adapted and redistributed under CC BY-SA 4.0 provided
attribution is preserved and the adaptation is itself licensed CC BY-SA 4.0. This project does
**not** use any NonCommercial (NC) or NoDerivatives (ND) dataset; those are not accepted on
Wikimedia Commons.

Note the share-alike direction: our outputs are *not* relicensable to CC BY 4.0 or to a public
domain dedication, because they are adaptations of CC BY 4.0 material redistributed under
CC BY-SA 4.0.

The Forest Service cession dataset and Royce's 1899 report are U.S. Government works and are
public domain in the United States, so they impose no upstream restriction. They are still
credited explicitly: the digitisation is someone's labour, and the 1899 schedule carries its
own interpretive choices. Combining public-domain material with CC BY-SA 4.0 material does not
relicense the public-domain parts, but a figure that mixes both is distributed under CC BY-SA
4.0 as a whole.

## When a source changes

Record the version in `site/data/polities.json` (`source.version`, `source.doi`) so any published
SVG can be traced back to the exact release it came from. If Cliopatria ships a new major
version, figures generated from the old one should be re-generated rather than silently edited.
