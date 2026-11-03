"""00b — Download geography + population reference files used by geo.py (run before 01b).

  data/raw/census_geo/cb_2020_us_county_500k.zip          2020 cartographic boundary counties
  data/raw/census_geo/ct_cou_to_cousub_crosswalk.txt     CT legacy county <-> planning region (town level)
  data/raw/census_pep/co-est00int-tot.csv, co-est2020-alldata.csv, co-est2025-alldata.csv, sub-est2025_9.csv
  data/raw/medill/the_state_of_local_news_2025.pdf       Medill report (national totals only)
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import RAW, UA, log_failure, today, write_source_md

FILES = {
    RAW / "census_geo/cb_2020_us_county_500k.zip": "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip",
    RAW / "census_geo/ct_cou_to_cousub_crosswalk.txt": "https://www2.census.gov/geo/docs/reference/ct_change/ct_cou_to_cousub_crosswalk.txt",
    RAW / "census_pep/co-est00int-tot.csv": "https://www2.census.gov/programs-surveys/popest/datasets/2000-2010/intercensal/county/co-est00int-tot.csv",
    RAW / "census_pep/co-est2020-alldata.csv": "https://www2.census.gov/programs-surveys/popest/datasets/2010-2020/counties/totals/co-est2020-alldata.csv",
    RAW / "census_pep/co-est2025-alldata.csv": "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv",
    RAW / "census_pep/sub-est2025_9.csv": "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/cities/totals/sub-est2025_9.csv",
    RAW / "medill/the_state_of_local_news_2025.pdf": "https://localnewsinitiative.northwestern.edu/assets/slnp/the_state_of_local_news_2025.pdf",
}
for f, url in FILES.items():
    f.parent.mkdir(parents=True, exist_ok=True)
    if f.exists() and f.stat().st_size > 1000:
        continue
    try:
        r = requests.get(url, headers=UA, timeout=300)
        r.raise_for_status()
        f.write_bytes(r.content)
    except Exception as e:  # noqa
        log_failure("census reference files", url, repr(e)[:200])

geo_md = RAW / "census_geo" / "SOURCE.md"
if not geo_md.exists():
    write_source_md(RAW / "census_geo", f"""
# Census geography reference files
- https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip (2020 cartographic boundary, 1:500k)
- https://www2.census.gov/geo/docs/reference/ct_change/ct_cou_to_cousub_crosswalk.txt (CT towns: legacy county <-> planning region)
- Access date: {today()}. Public domain.
""")
