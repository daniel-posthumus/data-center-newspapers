"""21 — USDA ERS Rural-Urban Continuum Codes (2023, 2013) and Urban Influence Codes (2024, 2013).

Pages: https://www.ers.usda.gov/data-products/rural-urban-continuum-codes
       https://www.ers.usda.gov/data-products/urban-influence-codes
RUCC 2023 and UIC 2024 use the 2022+ Connecticut planning regions (09110-09190). The 2013
vintages use the 8 legacy CT counties, so we add those 8 rows with rucc/uic filled from 2013
(rucc_year/uic_year = 2013 flags them). rucc2013/uic2013 columns are filled wherever the fips
matches the 2013 file.

Output: data/clean/rucc_uic.parquet
    fips, rucc, rucc_year, uic, uic_year, metro, rucc2013, uic2013
"""
import sys
import warnings
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, RAW, UA, log_failure, progress, today, write_source_md

warnings.filterwarnings("ignore")
ERS = "https://www.ers.usda.gov/media"
FILES = {
    "rucc2023": f"{ERS}/5768/2023-rural-urban-continuum-codes.csv",
    "rucc2013": f"{ERS}/5769/2013-rural-urban-continuum-codes.xls",
    "uic2024": f"{ERS}/6182/2024-urban-influence-codes.csv",
    "uic2013": f"{ERS}/6183/2013-urban-influence-codes.xls",
}
out = RAW / "ers_rucc_uic"
out.mkdir(parents=True, exist_ok=True)
paths = {}
for k, url in FILES.items():
    f = out / url.rsplit("/", 1)[1]
    if not (f.exists() and f.stat().st_size > 1000):
        try:
            r = requests.get(url, headers=UA, timeout=120)
            r.raise_for_status()
            f.write_bytes(r.content)
        except Exception as e:  # noqa
            log_failure("USDA ERS RUCC/UIC", url, repr(e)[:200])
            raise
    paths[k] = f


def long_csv(f, attr, fipscol):
    d = pd.read_csv(f, dtype=str, encoding="latin-1")
    d = d[d["Attribute"] == attr]
    return pd.DataFrame({"fips": d[fipscol].str.zfill(5), "v": pd.to_numeric(d["Value"]).astype("Int64")})


r23 = long_csv(paths["rucc2023"], "RUCC_2023", "FIPS").rename(columns={"v": "rucc"})
u24 = long_csv(paths["uic2024"], "UIC_2024", "FIPS-UIC").rename(columns={"v": "uic"})
r13 = pd.read_excel(paths["rucc2013"], dtype=str)
r13 = pd.DataFrame({"fips": r13["FIPS"].str.zfill(5), "rucc2013": pd.to_numeric(r13["RUCC_2013"]).astype("Int64")})
u13 = pd.read_excel(paths["uic2013"], dtype=str)
u13 = pd.DataFrame({"fips": u13["FIPS"].str.zfill(5), "uic2013": pd.to_numeric(u13["UIC_2013"]).astype("Int64")})
for d in (r23, u24, r13, u13):
    assert d["fips"].is_unique

df = r23.merge(u24, on="fips", how="outer")
df["rucc_year"] = pd.Series(2023, index=df.index, dtype="Int64").where(df["rucc"].notna())
df["uic_year"] = pd.Series(2024, index=df.index, dtype="Int64").where(df["uic"].notna())

# add legacy CT counties from 2013
ct = r13[r13.fips.str.match(r"^090(0[1-9]|1[0-5])$")].merge(u13, on="fips")
ct = ct.assign(rucc=ct["rucc2013"], uic=ct["uic2013"], rucc_year=2013, uic_year=2013)
df = pd.concat([df, ct[["fips", "rucc", "uic", "rucc_year", "uic_year"]]], ignore_index=True)
df = df.merge(r13, on="fips", how="left").merge(u13, on="fips", how="left")
for c in ["rucc_year", "uic_year"]:
    df[c] = df[c].astype("Int64")

n0 = len(df)
df = df[(df.fips.str[:2].astype(int) <= 56) & (df.fips.str[:2] != "00")].copy()
n_drop = n0 - len(df)
df["metro"] = (df["rucc"] <= 3).astype("Int64")
df = df[["fips", "rucc", "rucc_year", "uic", "uic_year", "metro", "rucc2013", "uic2013"]].sort_values("fips")
assert df.fips.is_unique
df.to_parquet(CLEAN / "rucc_uic.parquet", index=False)

msg = (f"RUCC/UIC: {len(df)} rows (dropped {n_drop} PR/territory rows); RUCC2023 non-missing {df.rucc_year.eq(2023).sum()}, "
       f"UIC2024 non-missing {df.uic_year.eq(2024).sum()}; metro counties (2023 rows) {int(df.loc[df.rucc_year.eq(2023), 'metro'].sum())}; "
       f"8 legacy CT counties added from 2013; rucc2013 matched {df.rucc2013.notna().sum()}")
print(msg)
print(df.rucc.value_counts().sort_index())
progress(msg)

write_source_md(out, f"""
# USDA ERS Rural-Urban Continuum Codes and Urban Influence Codes

- RUCC 2023: {FILES['rucc2023']}
- RUCC 2013: {FILES['rucc2013']}
- UIC 2024: {FILES['uic2024']}
- UIC 2013: {FILES['uic2013']}
- Landing pages: https://www.ers.usda.gov/data-products/rural-urban-continuum-codes , https://www.ers.usda.gov/data-products/urban-influence-codes
- Access date: {today()}
- Vintage: RUCC 2023 / UIC 2024 are based on 2020 Census + 2023 OMB delineations and use the
  Connecticut PLANNING REGIONS (09110-09190). RUCC/UIC 2013 use 2010-era counties (legacy CT
  counties 09001-09015; also 2010-era codes like 02261, 46113, 51515).
- In the clean file the 8 legacy CT counties are added as extra rows with rucc/uic taken from 2013
  (rucc_year/uic_year = 2013). CT planning-region rows are kept too (rucc_year 2023).
- License: USDA ERS public-domain data.
- Result: {msg}
""")
