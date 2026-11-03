"""20 — ACS 5-year 2017-2021 county covariates from the table-based Summary File (no API key).

Source (bulk, keyless):
    https://www2.census.gov/programs-surveys/acs/summary_file/2021/table-based-SF/data/5YRData/acsdt5y2021-<table>.dat
Land area: 2021 Census Gazetteer county file
    https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2021_Gazetteer/2021_Gaz_counties_national.zip
ACS 2021 uses 2020-era county geography with the 8 legacy Connecticut counties
(planning regions enter only in ACS 2022).

Output: data/clean/acs_county_2021.parquet
    fips, pop_acs, aland_sqmi, density, med_hh_income, sh_65plus, sh_ba_plus, sh_white_nh
"""
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, RAW, UA, log_failure, progress, today, write_source_md

BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/2021/table-based-SF"
GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2021_Gazetteer/2021_Gaz_counties_national.zip"
TABLES = ["b01003", "b01001", "b03002", "b15003", "b19013"]
out = RAW / "acs"
out.mkdir(parents=True, exist_ok=True)


def fetch(url, f):
    if f.exists() and f.stat().st_size > 1000:
        return f
    for attempt in range(3):
        try:
            with requests.get(url, headers=UA, timeout=600, stream=True) as r:
                r.raise_for_status()
                tmp = f.with_suffix(f.suffix + ".part")
                with tmp.open("wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
                tmp.rename(f)
            return f
        except Exception as e:  # noqa
            time.sleep(5)
            if attempt == 2:
                log_failure("ACS 5yr 2021 summary file", url, repr(e)[:200])
                raise


fetch(f"{BASE}/documentation/ACS20215YR_Table_Shells.txt", out / "ACS20215YR_Table_Shells.txt")
fetch(f"{BASE}/documentation/Geos20215YR.txt", out / "Geos20215YR.txt")
for t in TABLES:
    fetch(f"{BASE}/data/5YRData/acsdt5y2021-{t}.dat", out / f"acsdt5y2021-{t}.dat")
fetch(GAZ, out / "2021_Gaz_counties_national.zip")

# Verify the cell definitions we rely on against the shells file
shells = pd.read_csv(out / "ACS20215YR_Table_Shells.txt", sep="|", dtype=str, encoding="utf-8-sig")
lab = dict(zip(shells["Unique ID"], shells["Label"]))
for k, v in {"B15003_022": "Bachelor", "B15003_025": "Doctorate", "B01001_020": "65 and 66",
             "B01001_049": "85 years", "B03002_003": "White alone", "B19013_001": "Median"}.items():
    assert v.lower() in lab[k].lower(), (k, lab[k])


def read_county(t):
    """Read only county rows (GEO_ID 0500000USssccc) from a pipe-delimited table file."""
    keep = []
    for chunk in pd.read_csv(out / f"acsdt5y2021-{t}.dat", sep="|", dtype=str, chunksize=500_000):
        keep.append(chunk[chunk["GEO_ID"].str.startswith("0500000US")])
    d = pd.concat(keep)
    d["fips"] = d["GEO_ID"].str[-5:]
    d = d.set_index("fips")
    return d[[c for c in d.columns if "_E" in c]].apply(pd.to_numeric, errors="coerce")


b01003 = read_county("b01003")
b01001 = read_county("b01001")
b03002 = read_county("b03002")
b15003 = read_county("b15003")
b19013 = read_county("b19013")

df = pd.DataFrame(index=b01003.index)
df["pop_acs"] = b01003["B01003_E001"]
old = [f"B01001_E{i:03d}" for i in list(range(20, 26)) + list(range(44, 50))]
df["sh_65plus"] = b01001[old].sum(axis=1) / b01001["B01001_E001"]
ba = [f"B15003_E{i:03d}" for i in range(22, 26)]
df["sh_ba_plus"] = b15003[ba].sum(axis=1) / b15003["B15003_E001"]
df["sh_white_nh"] = b03002["B03002_E003"] / b03002["B03002_E001"]
df["med_hh_income"] = b19013["B19013_E001"]  # ACS jam values (e.g. -666666666) -> NA below
df.loc[df["med_hh_income"] < 0, "med_hh_income"] = pd.NA

# Gazetteer land area (ALAND_SQMI)
with zipfile.ZipFile(out / "2021_Gaz_counties_national.zip") as z:
    name = [n for n in z.namelist() if n.endswith(".txt")][0]
    gaz = pd.read_csv(z.open(name), sep="\t", dtype={"GEOID": str})
gaz.columns = [c.strip() for c in gaz.columns]
gaz = gaz.set_index(gaz["GEOID"].str.zfill(5))
df["aland_sqmi"] = gaz["ALAND_SQMI"].reindex(df.index)
df["density"] = df["pop_acs"] / df["aland_sqmi"]

df = df.reset_index()
n0 = len(df)
df = df[~df["fips"].str[:2].isin(["60", "66", "69", "72", "78"])].copy()
n_drop = n0 - len(df)
df = df[["fips", "pop_acs", "aland_sqmi", "density", "med_hh_income", "sh_65plus", "sh_ba_plus", "sh_white_nh"]]
df.to_parquet(CLEAN / "acs_county_2021.parquet", index=False)

ct = sorted(df.loc[df.fips.str[:2] == "09", "fips"])
msg = (f"ACS 2021 5yr: {len(df)} counties (dropped {n_drop} PR rows), national pop {df.pop_acs.sum():,.0f}, "
       f"missing aland {df.aland_sqmi.isna().sum()}, missing med income {df.med_hh_income.isna().sum()}, CT fips {ct}")
print(msg)
print(df.describe().T)
progress(msg)

write_source_md(out, f"""
# ACS 5-year 2017-2021, table-based Summary File + 2021 Gazetteer counties

- Tables: {', '.join(t.upper() for t in TABLES)}
- URL pattern: {BASE}/data/5YRData/acsdt5y2021-<table>.dat (pipe-delimited, all geographies; county rows = GEO_ID 0500000USsscc c)
- Documentation: {BASE}/documentation/ACS20215YR_Table_Shells.txt, Geos20215YR.txt
- Land area: {GAZ} (ALAND_SQMI)
- Access date: {today()}
- Vintage: ACS 2017-2021 5-year estimates; 2021 Gazetteer. County geography = 2020-era counties,
  Connecticut = 8 legacy counties (09001-09015), no planning regions.
- License: U.S. Census Bureau public-domain data.
- Derived (by code/20_pull_acs.py): pop_acs=B01003_001; sh_65plus=B01001_020..025+044..049 / B01001_001;
  sh_ba_plus=B15003_022..025 / B15003_001; sh_white_nh=B03002_003/B03002_001; med_hh_income=B19013_001;
  density = pop_acs / ALAND_SQMI.
- Result: {msg}
""")
