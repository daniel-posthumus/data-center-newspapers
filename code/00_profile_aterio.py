"""00 — Profile the Aterio inventory (2026-06-30 vintage) and build facility/campus files.

Inputs : data/raw/aterio/2026-06-30/data_center_inventory_20260630.csv
         data/raw/aterio/2026-02-09/...Weekly Report 20260209.xlsx (second snapshot, 12 fields)
Outputs: output/tables/aterio_*.{csv,md}, output/logs/00_profile_aterio.txt
         data/intermediate/aterio_facility.parquet  (US facilities, parsed; county FIPS not yet filled)
         data/intermediate/aterio_feb_snapshot.parquet
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from config import ATERIO_CSV, INTER, OUTLOGS, RAW, progress, save_table

log_lines = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    log_lines.append(s)


raw = pd.read_csv(ATERIO_CSV, dtype=str, keep_default_na=False)
log(f"Raw rows: {len(raw)}  columns: {raw.shape[1]}")
log("Rows by country:\n" + raw.COUNTRY_CODE.value_counts().to_string())
assert raw.ATERIO_DATA_CENTER_UID.is_unique, "facility UID not unique"

d = raw.replace({"": np.nan}).copy()
d["is_us"] = d.COUNTRY_CODE.eq("US")

# ------------------------------------------------------------------ stage counts
st = (
    d.groupby(["DATA_CENTER_STAGE", "COUNTRY_CODE"]).size().unstack(fill_value=0)
    .assign(total=lambda x: x.sum(axis=1)).sort_values("total", ascending=False)
)
st.loc["Total"] = st.sum()
save_table(st.reset_index(), "aterio_stage_counts_facility")
log("\nFacility rows by stage x country:\n" + st.to_string())

us = d[d.is_us].copy()
log(f"\nUS facility rows: {len(us)}  (Canada dropped: {(~d.is_us).sum()})")

# ------------------------------------------------------------------ facility vs campus
us["campus_uid_missing"] = us.ATERIO_DATA_CENTER_CAMPUS_UID.isna()
log(f"US facilities with missing campus UID: {us.campus_uid_missing.sum()}")
us["campus_id"] = us.ATERIO_DATA_CENTER_CAMPUS_UID.fillna("SOLO_" + us.ATERIO_DATA_CENTER_UID)
bpc = us.groupby("campus_id").size()
log(f"US campuses (campus UID, singletons for missing): {bpc.size}")
fc = pd.DataFrame({
    "metric": ["US facilities", "US campuses", "campuses with 1 building", "campuses with 2-5",
               "campuses with 6+", "max buildings in a campus", "mean buildings per campus"],
    "value": [len(us), bpc.size, (bpc == 1).sum(), bpc.between(2, 5).sum(), (bpc >= 6).sum(),
              bpc.max(), round(bpc.mean(), 3)],
})
save_table(fc, "aterio_facility_vs_campus")
log(fc.to_string(index=False))

# ------------------------------------------------------------------ missingness
fields = [
    "ATERIO_DATA_CENTER_UID", "ATERIO_DATA_CENTER_CAMPUS_UID", "DATA_CENTER_STAGE",
    "PROJECT_EXECUTION_LIKELIHOOD", "FLG_AI_FACILITY", "FLG_BTM_ONSITE_POWER_GENERATION",
    "PROVIDER_NAME", "PROVIDER_PUBLIC_PRIVATE", "END_USER_COMPANIES", "COUNTY_FIPS_CODE",
    "PLACE_FIPS_CODE", "LOCATION_LATITUDE", "LOCATION_LONGITUDE",
    "PROV_PUB_TOT_POWER_CAPACITY_MW", "ATERIO_EST_TOT_POWER_CAPACITY_MW",
    "SELECTED_POWER_CAPACITY_MW", "DATA_CENTER_ANNOUNCED_DATE", "DATA_CENTER_CANCELLED_DATE",
    "DATA_CENTER_PROJECT_WITHDRAWN_DATE", "DATA_CENTER_CONSTRUCTION_START_DATE",
    "DATA_CENTER_ACTIVATION_DATE", "RECORD_CREATED_DATE", "RECORD_UPDATED_DATE",
    "UTILITY_CODE", "UTILITY_NAME", "BAL_AUTH_ABBR", "PROJECT_PERMIT_URL", "DATASHEET_URL", "NOTES",
]
miss = pd.DataFrame({
    "field": fields,
    "n_missing": [us[f].isna().sum() for f in fields],
})
miss["pct_missing"] = 100 * miss.n_missing / len(us)
# note: the AI / BTM flags are blank-or-Y fields, so "missing" largely means "not flagged"
miss["note"] = ""
miss.loc[miss.field.isin(["FLG_AI_FACILITY", "FLG_BTM_ONSITE_POWER_GENERATION"]), "note"] = (
    "blank = not flagged (values are Y / N / blank)")
miss.loc[miss.field.isin(["DATA_CENTER_CANCELLED_DATE", "DATA_CENTER_PROJECT_WITHDRAWN_DATE"]), "note"] = (
    "expected missing unless cancelled/withdrawn")
save_table(miss, "aterio_missingness_us_facility", floatfmt=".1f")
log("\nMissingness (US facilities):\n" + miss.to_string(index=False))
log("\nFLG_AI_FACILITY values:\n" + us.FLG_AI_FACILITY.value_counts(dropna=False).to_string())
log("FLG_BTM values:\n" + us.FLG_BTM_ONSITE_POWER_GENERATION.value_counts(dropna=False).to_string())

# ------------------------------------------------------------------ dates
date_cols = [c for c in us.columns if c.endswith("_DATE") or c == "UPDATED_AT"]
for c in date_cols:
    us[c] = pd.to_datetime(us[c].str[:10], errors="coerce")
dr = pd.DataFrame({
    "field": date_cols,
    "n_nonmissing": [us[c].notna().sum() for c in date_cols],
    "min": [us[c].min() for c in date_cols],
    "max": [us[c].max() for c in date_cols],
})
save_table(dr, "aterio_date_ranges_us")
log("\nDate ranges (US):\n" + dr.to_string(index=False))

ann = us.DATA_CENTER_ANNOUNCED_DATE.dt.year.value_counts(dropna=False).sort_index()
anndf = ann.rename_axis("announced_year").reset_index(name="n_facilities")
anndf["announced_year"] = anndf.announced_year.astype("Int64").astype(str).replace("<NA>", "missing")
save_table(anndf, "aterio_announced_year_us_facility")
log("\nAnnounced year (US facilities):\n" + anndf.to_string(index=False))

# ------------------------------------------------------------------ undisclosed
pn = us.PROVIDER_NAME.fillna("").str.strip().str.lower()
pat = r"not\s*disclos|undisclos|unknown|confidential|unnamed|anonymous|^n/?a$|^tbd|to be determined|^none$|stealth"
variants = us.PROVIDER_NAME[pn.str.contains(pat, regex=True)].value_counts()
log("\nProvider-name variants matching non-disclosure pattern:\n" + variants.to_string())
log(f"Missing PROVIDER_NAME: {us.PROVIDER_NAME.isna().sum()}")
us["undisclosed"] = pn.str.contains(pat, regex=True).astype(int)
us["no_end_user"] = us.END_USER_COMPANIES.isna().astype(int)
und = pd.DataFrame({
    "metric": ["US facilities 'Company Not Disclosed' (any variant)", "share",
               "US facilities with no END_USER_COMPANIES", "share"],
    "value": [us.undisclosed.sum(), us.undisclosed.mean(), us.no_end_user.sum(), us.no_end_user.mean()],
})
save_table(und, "aterio_undisclosed_counts")
log(und.to_string(index=False))
log("\nUndisclosed by stage:\n" + pd.crosstab(us.DATA_CENTER_STAGE, us.undisclosed, margins=True).to_string())

# ------------------------------------------------------------------ links
for c in ["PROJECT_PERMIT_URL", "DATASHEET_URL"]:
    log(f"{c} populated: {us[c].notna().sum()} of {len(us)} ({100*us[c].notna().mean():.1f}%)")

# ------------------------------------------------------------------ within-campus heterogeneity
g = us.groupby("campus_id")
het = pd.DataFrame({
    "attribute": ["county FIPS", "stage", "provider", "announced date"],
    "campuses_with_>1_distinct_value": [
        (g.COUNTY_FIPS_CODE.nunique() > 1).sum(), (g.DATA_CENTER_STAGE.nunique() > 1).sum(),
        (g.PROVIDER_NAME.nunique() > 1).sum(), (g.DATA_CENTER_ANNOUNCED_DATE.nunique() > 1).sum()],
})
save_table(het, "aterio_within_campus_heterogeneity")
log("\nWithin-campus heterogeneity (number of campuses):\n" + het.to_string(index=False))

# numeric
for c in ["SELECTED_POWER_CAPACITY_MW", "PROV_PUB_TOT_POWER_CAPACITY_MW", "ATERIO_EST_TOT_POWER_CAPACITY_MW",
          "LOCATION_LATITUDE", "LOCATION_LONGITUDE", "SITE_ACREAGE", "TOT_PROJECT_COST", "PCT_CONSTRUCTION_STATUS"]:
    us[c] = pd.to_numeric(us[c], errors="coerce")
log("\nSELECTED_POWER_CAPACITY_MW describe:\n" + us.SELECTED_POWER_CAPACITY_MW.describe().to_string())

us.to_parquet(INTER / "aterio_facility.parquet", index=False)

# ------------------------------------------------------------------ Feb 2026 snapshot
feb = pd.read_excel(RAW / "aterio/2026-02-09/Aterio US Data Centers Weekly Report 20260209.xlsx",
                    sheet_name="US Data Centers Dataset")
feb = feb.rename(columns={"ATERIO_DATACENTER_UNIQUE_ID": "ATERIO_DATA_CENTER_UID",
                          "PROVIDER_NAME": "PROVIDER_NAME_FEB", "DATACENTER_STAGE": "STAGE_FEB",
                          "RECORD_UPDATED_DATE": "RECORD_UPDATED_DATE_FEB"})
feb = feb[["ATERIO_DATA_CENTER_UID", "PROVIDER_NAME_FEB", "STAGE_FEB", "RECORD_UPDATED_DATE_FEB"]]
log(f"\nFeb-2026 snapshot rows: {len(feb)}; unique UIDs: {feb.ATERIO_DATA_CENTER_UID.nunique()}")
m = us[["ATERIO_DATA_CENTER_UID"]].merge(feb, on="ATERIO_DATA_CENTER_UID", how="outer", indicator=True)
log("Feb vs Jun UID match:\n" + m._merge.value_counts().to_string())
feb.to_parquet(INTER / "aterio_feb_snapshot.parquet", index=False)

(OUTLOGS / "00_profile_aterio.txt").write_text("\n".join(log_lines) + "\n")
progress("00_profile_aterio done: US facilities=%d, campuses=%d" % (len(us), bpc.size))
