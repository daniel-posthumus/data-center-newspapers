"""24 — USDA NASS Census of Agriculture: county value of ag land & buildings per acre (2012, 2017, 2022).

QuickStats API needs a free key (keyless -> HTTP 401 {"error":["unauthorized"]}); we have none.
Instead: the keyless QuickStats bulk file  https://www.nass.usda.gov/datasets/qs.economics_YYYYMMDD.txt.gz
(the date in the name changes; the current name is read from https://www.nass.usda.gov/datasets/).
Filter: SOURCE_DESC=CENSUS, SHORT_DESC="AG LAND, INCL BUILDINGS - ASSET VALUE, MEASURED IN $ / ACRE",
AGG_LEVEL_DESC=COUNTY, DOMAIN_DESC=TOTAL, YEAR in {2012, 2017, 2022}.
County code 998 ("OTHER (COMBINED) COUNTIES") rows are dropped. "(D)" = withheld to avoid disclosing
individual operations -> land_value_per_acre NaN, suppressed=1.

Output: data/clean/nass_landvalue.parquet
    fips, year, land_value_per_acre, suppressed, value_raw
"""
import gzip
import re
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, RAW, UA, log_failure, progress, today, write_source_md

ITEM = "AG LAND, INCL BUILDINGS - ASSET VALUE, MEASURED IN $ / ACRE"
YEARS = {"2012", "2017", "2022"}
TERR = {"60", "66", "69", "72", "78"}
out = RAW / "nass"
out.mkdir(parents=True, exist_ok=True)

# 1. API (expected to fail without key) -- logged for the memo
r = requests.get("https://quickstats.nass.usda.gov/api/api_GET/", params={"format": "JSON", "short_desc": ITEM},
                 headers=UA, timeout=60)
if r.status_code != 200:
    log_failure("USDA NASS QuickStats API", "county ag land value $/acre",
                f"API requires free key (keyless HTTP {r.status_code}); used keyless bulk file qs.economics_*.txt.gz instead")

# 2. bulk file (reuse an existing local copy if present)
local = sorted(out.glob("qs.economics_*.txt.gz"))
if local:
    gz = local[-1]
else:
    html = requests.get("https://www.nass.usda.gov/datasets/", headers=UA, timeout=60).text
    name = sorted(set(re.findall(r"qs\.economics_\d{8}\.txt\.gz", html)))[-1]
    url = f"https://www.nass.usda.gov/datasets/{name}"
    gz = out / name
    try:
        with requests.get(url, headers=UA, timeout=1800, stream=True) as resp:
            resp.raise_for_status()
            tmp = gz.with_suffix(".part")
            with tmp.open("wb") as fh:
                for chunk in resp.iter_content(1 << 22):
                    fh.write(chunk)
            tmp.rename(gz)
    except Exception as e:  # noqa
        log_failure("USDA NASS QuickStats bulk", url, repr(e)[:200])
        raise

rows = []
with gzip.open(gz, "rt", encoding="utf-8", errors="replace") as fh:
    header = fh.readline().rstrip("\n").split("\t")
    ix = {c: i for i, c in enumerate(header)}
    for line in fh:
        if ITEM not in line:
            continue
        f = line.rstrip("\n").split("\t")
        if (f[ix["SHORT_DESC"]] == ITEM and f[ix["SOURCE_DESC"]] == "CENSUS" and f[ix["AGG_LEVEL_DESC"]] == "COUNTY"
                and f[ix["DOMAIN_DESC"]] == "TOTAL" and f[ix["YEAR"]] in YEARS):
            rows.append({c: f[ix[c]] for c in ["STATE_FIPS_CODE", "COUNTY_CODE", "COUNTY_NAME", "STATE_ALPHA",
                                                 "YEAR", "VALUE", "REFERENCE_PERIOD_DESC", "FREQ_DESC"]})
d = pd.DataFrame(rows)
print("raw matched rows:", len(d), d.groupby("YEAR").size().to_dict())
n_998 = int((d["COUNTY_CODE"] == "998").sum())
d = d[d["COUNTY_CODE"] != "998"].copy()
d["fips"] = d["STATE_FIPS_CODE"].str.zfill(2) + d["COUNTY_CODE"].str.zfill(3)
n0 = len(d)
d = d[~d["fips"].str[:2].isin(TERR)]
n_terr = n0 - len(d)
d["value_raw"] = d["VALUE"].str.strip()
d["land_value_per_acre"] = pd.to_numeric(d["value_raw"].str.replace(",", ""), errors="coerce")
d["suppressed"] = (d["value_raw"] == "(D)").astype(int)
d["year"] = d["YEAR"].astype(int)
other_nonnum = d.loc[d.land_value_per_acre.isna() & (d.suppressed == 0), "value_raw"].value_counts().to_dict()
assert not d.duplicated(["fips", "year"]).any()
d = d[["fips", "year", "land_value_per_acre", "suppressed", "value_raw"]].sort_values(["year", "fips"])
d.to_parquet(CLEAN / "nass_landvalue.parquet", index=False)

summ = d.groupby("year").agg(n=("fips", "size"), n_suppressed=("suppressed", "sum"),
                             median=("land_value_per_acre", "median"), mean=("land_value_per_acre", "mean"))
ct = {y: sorted(d[(d.year == y) & (d.fips.str[:2] == "09")].fips) for y in sorted(d.year.unique())}
print(summ)
msg = (f"NASS land value/acre: {len(d)} rows; by year {summ.n.to_dict()}; suppressed (D) {summ.n_suppressed.to_dict()}; "
       f"other non-numeric {other_nonnum}; dropped {n_998} '998 other combined' rows and {n_terr} territory rows; "
       f"CT fips {ct}")
print(msg)
progress(msg)

write_source_md(out, f"""
# USDA NASS Quick Stats bulk file (economics sector)

- File: https://www.nass.usda.gov/datasets/{gz.name} (listing: https://www.nass.usda.gov/datasets/)
- Access date: {today()}
- Vintage: Quick Stats snapshot {gz.name[13:21]}; extracted Census of Agriculture 2012, 2017, 2022.
- Item: "{ITEM}", SOURCE_DESC=CENSUS, AGG_LEVEL_DESC=COUNTY, DOMAIN_DESC=TOTAL.
- QuickStats API requires a free key (keyless -> HTTP 401); not used.
- License: USDA NASS public-domain data.
- Raw gz kept untouched; only the extracted subset is in data/clean/nass_landvalue.parquet.
- "(D)" = withheld to avoid disclosing data for individual operations.
- Coverage (checked vs ACS 2021 county list): ~66-67 counties absent each year: 35 Virginia independent
  cities (NASS folds them into surrounding counties), Alaska (NASS reports 5 own areas 02010, 02020,
  02090, 02110, 02122 -- 02010 "Aleutian Islands" is not a current FIPS), plus a few urban units
  (e.g. 08014, 11001, 15005, 24510, 29510). CT = 8 legacy counties in all years.

## Result
{msg}

{summ.to_markdown()}
""")
