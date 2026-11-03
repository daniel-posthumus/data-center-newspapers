"""23 — Census of Governments: counts of local governments per county (2022, CT from 2017).

Source: Census Government Units lists (individual government units, with county FIPS)
    https://www2.census.gov/programs-surveys/gus/datasets/2022/govt_units_2022.ZIP
    https://www2.census.gov/programs-surveys/gus/datasets/2017/govt_units_2017.ZIP
Each unit is assigned to ONE county (FIPS_STATE+FIPS_COUNTY); multi-county municipalities and
districts are counted only in that county.
CoG 2022 codes Connecticut by planning region (09110-09190). We keep those rows (cog_year 2022)
and ADD the 8 legacy CT counties from CoG 2017 (cog_year 2017).
Dependent school systems (sheet "DEP School Dist") are not governments and are not counted.

Output: data/clean/cog_county.parquet
    fips, n_county_gov, n_municipal, n_township, n_general_purpose, n_special_district,
    n_school_district, n_total_local, cog_year
"""
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, RAW, UA, log_failure, progress, today, write_source_md

out = RAW / "cog"
out.mkdir(parents=True, exist_ok=True)
URL = "https://www2.census.gov/programs-surveys/gus/datasets/{y}/govt_units_{y}.ZIP"
TERR = {"60", "66", "69", "72", "78"}
for y in (2022, 2017):
    f = out / f"govt_units_{y}.ZIP"
    if not (f.exists() and f.stat().st_size > 1e6):
        try:
            r = requests.get(URL.format(y=y), headers=UA, timeout=300)
            r.raise_for_status()
            f.write_bytes(r.content)
        except Exception as e:  # noqa
            log_failure("Census of Governments", f"govt_units_{y}", repr(e)[:200])
            raise


def load(y):
    with zipfile.ZipFile(out / f"govt_units_{y}.ZIP") as z:
        n = [m for m in z.namelist() if m.lower().endswith(".xlsx")][0]
        x = pd.read_excel(z.open(n), sheet_name=None, dtype=str)
    gp = x["General Purpose"]
    sd = x["Special District"]
    sc = x["School District"]
    units = pd.concat([
        gp.assign(kind=gp["UNIT_TYPE"].str[0].map({"1": "county", "2": "municipal", "3": "township"})),
        sd.assign(kind="special"), sc.assign(kind="school")], ignore_index=True)
    assert units["kind"].notna().all()
    units["fips"] = units["FIPS_STATE"].str.zfill(2) + units["FIPS_COUNTY"].str.zfill(3)
    return units


u22 = load(2022)
u17 = load(2017)
nat22 = u22["kind"].value_counts().to_dict()
nat17 = u17["kind"].value_counts().to_dict()
print("2022 national counts:", nat22)
print("2017 national counts:", nat17)


def counts(u, y):
    c = pd.crosstab(u["fips"], u["kind"]).reindex(columns=["county", "municipal", "township", "special", "school"], fill_value=0)
    c = c.rename(columns={"county": "n_county_gov", "municipal": "n_municipal", "township": "n_township",
                          "special": "n_special_district", "school": "n_school_district"})
    c["n_general_purpose"] = c[["n_county_gov", "n_municipal", "n_township"]].sum(axis=1)
    c["n_total_local"] = c[["n_general_purpose", "n_special_district", "n_school_district"]].sum(axis=1)
    c["cog_year"] = y
    return c.reset_index()


c22 = counts(u22, 2022)
c17 = counts(u17, 2017)
ct17 = c17[c17["fips"].isin([f"090{i:02d}" for i in range(1, 16, 2)])]
df = pd.concat([c22, ct17], ignore_index=True)
n0 = len(df)
df = df[~df["fips"].str[:2].isin(TERR)]
n_terr = n0 - len(df)
df = df[["fips", "n_county_gov", "n_municipal", "n_township", "n_general_purpose", "n_special_district",
         "n_school_district", "n_total_local", "cog_year"]].sort_values("fips")
assert df["fips"].is_unique
df.to_parquet(CLEAN / "cog_county.parquet", index=False)

# odd county codes (not a county in the 2021 Gazetteer / ACS county list), for the record
odd = []
acs = CLEAN / "acs_county_2021.parquet"
if acs.exists():
    valid = set(pd.read_parquet(acs)["fips"]) | {f"091{i}0" for i in range(1, 10)}
    odd = df.loc[~df["fips"].isin(valid), ["fips", "n_total_local", "cog_year"]].to_dict("records")
msg = (f"CoG: {len(df)} county rows ({len(c22)} from 2022 incl. CT planning regions, + {len(ct17)} legacy CT from 2017); "
       f"dropped {n_terr} territory rows; 2022 national: county {nat22.get('county')}, municipal {nat22.get('municipal')}, "
       f"township {nat22.get('township')}, special {nat22.get('special')}, school {nat22.get('school')}; "
       f"fips not in county list: {odd}")
print(msg)
progress(msg)

write_source_md(out, f"""
# Census of Governments — Government Units lists

- 2022: {URL.format(y=2022)} (Govt_Units_2022_Final.xlsx, dated 2023-08-21)
- 2017: {URL.format(y=2017)} (Govt_Units_2017_Final.xlsx, dated 2020-02-13; the lowercase .zip on the server is an older 2019 upload)
- Access date: {today()}
- Vintage: CoG 2022 (units as of 2022) uses CONNECTICUT PLANNING REGIONS (09110-09190) for county codes;
  CoG 2017 uses the 8 legacy CT counties. Clean file keeps 2022 everywhere and adds the 8 legacy CT
  counties from 2017 (cog_year=2017).
- Each unit is assigned to one county (FIPS_COUNTY of the unit). Units flagged IS_ACTIVE='N' (2022: 96
  general-purpose, 242 special, 1 school) are kept so that totals match the official CoG counts.
- Dependent school systems are not counted.
- Counties with no unit assigned are ABSENT from the file (= zero units): 2022 -> 15005 Kalawao and the four
  NYC boroughs 36005/36047/36081/36085 (NYC is coded to 36061).
- License: U.S. Census Bureau public-domain data.
- Result: {msg}
- 2017 national counts: {nat17}
""")
