"""03 — County population panel 2005-2025 on the 2020 county universe (for per-10k measures).

Sources (data/raw/census_pep/, raw untouched):
  co-est00int-tot.csv     2000-2010 intercensal (2000-era counties) -> years 2005-2009
  co-est2020-alldata.csv  Vintage 2020 postcensal (2010-2020)        -> years 2010-2019
  co-est2025-alldata.csv  Vintage 2025 (2020-2025; CT planning regions) -> years 2020-2025
Output: data/clean/pop_county_year.parquet (fips, year, pop)
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, OUTLOGS, RAW, progress, today, write_source_md
from geo import county_list, harmonize

R = RAW / "census_pep"
rd = lambda f: pd.read_csv(R / f, dtype={"STATE": str, "COUNTY": str}, encoding="latin-1")

a = rd("co-est00int-tot.csv")
a = a[a.SUMLEV == 50]
a["fips"] = a.STATE.str.zfill(2) + a.COUNTY.str.zfill(3)
a = a.melt(id_vars="fips", value_vars=[f"POPESTIMATE{y}" for y in range(2005, 2010)],
           var_name="year", value_name="pop")

b = rd("co-est2020-alldata.csv")
b = b[b.SUMLEV == 50]
b["fips"] = b.STATE + b.COUNTY
b = b.melt(id_vars="fips", value_vars=[f"POPESTIMATE{y}" for y in range(2010, 2020)],
           var_name="year", value_name="pop")

c = rd("co-est2025-alldata.csv")
c = c[c.SUMLEV == 50]
c["fips"] = c.STATE + c.COUNTY
c = c.melt(id_vars="fips", value_vars=[f"POPESTIMATE{y}" for y in range(2020, 2026)],
           var_name="year", value_name="pop")

p = pd.concat([a, b, c])
p["year"] = p.year.str[-4:].astype(int)
p = p[p.fips.str[:2].astype(int) <= 56]
h = harmonize(p, "fips", count_cols=["pop"], by=["year"])
lines = [f"dropped (not in 2020 universe after mapping): {len(h.attrs['dropped'])} rows: "
         f"{sorted(set(h.attrs['dropped']))}"]
panel = pd.MultiIndex.from_product([county_list(), range(2005, 2026)], names=["fips", "year"]).to_frame(index=False)
h = panel.merge(h, on=["fips", "year"], how="left")
miss = h[h["pop"].isna()]
lines.append(f"county-years missing pop: {len(miss)}; counties: {sorted(miss.fips.unique())[:20]}")
tot = h.groupby("year")["pop"].sum()
lines.append("national total by year:\n" + tot.to_string())
h.to_parquet(CLEAN / "pop_county_year.parquet", index=False)
(OUTLOGS / "03_build_population.txt").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
write_source_md(R, f"""
# Census Population Estimates Program (PEP), county totals
- https://www2.census.gov/programs-surveys/popest/datasets/2000-2010/intercensal/county/co-est00int-tot.csv
- https://www2.census.gov/programs-surveys/popest/datasets/2010-2020/counties/totals/co-est2020-alldata.csv
- https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv
- https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/cities/totals/sub-est2025_9.csv (CT towns, for CT crosswalk weights)
- Access date: {today()}. Public domain (U.S. Government work).
- Vintage 2025 uses CT planning regions; harmonized to legacy counties via code/geo.py.
""")
progress("03 population panel built")
