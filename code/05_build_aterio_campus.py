"""05 — Aterio: assign 2020 counties, check stage coding (A5), aggregate to campuses, define outcomes.

County assignment: point-in-polygon of facility lat/lon in 2020 county polygons (primary);
fallback = Aterio COUNTY_FIPS_CODE harmonized to 2020 counties (non-CT only). Agreement reported.

Campus rule (documented in memo):
  campus_id      = ATERIO_DATA_CENTER_CAMPUS_UID; facilities with no campus UID are their own campus.
  ann_date       = earliest DATA_CENTER_ANNOUNCED_DATE among the campus's buildings.
  county / state / lat-lon / utility / BA = those of the earliest-announced building (if no building has a
                   date, the first building in file order); campuses spanning >1 county are flagged.
  mw             = sum of SELECTED_POWER_CAPACITY_MW over buildings (missing if all missing).
  ai, btm        = 1 if any building is flagged Y.
  undisclosed    = 1 if the campus provider is "Company Not Disclosed" (modal provider; 2 campuses mix).
  no_end_user    = 1 if no building lists END_USER_COMPANIES.
  failed         = 1 if ALL buildings are Not Approved/Withdrawn or Cancelled (failed_any = any building).
  constr_start   = earliest construction start date <= snapshot (2026-06-30); later dates are plans.
  stage_campus   = failed buildings aside, the most advanced stage among buildings
                   (Active > Construction > Delayed > Announcement > Land Bank); if all failed:
                   Cancelled if any building Cancelled, else Not Approved/Withdrawn.
  stalled_X      = not failed, stage_campus in {Announcement, Delayed, Land Bank}, no construction start
                   by the snapshot, and announced more than X months before the snapshot; defined only for
                   campuses announced at least X months before the snapshot. X = 24 primary; 12/18/36 robustness.
Outputs: data/clean/aterio_facility_geo.parquet, data/clean/aterio_campus.parquet,
         output/tables/a5_*.csv, output/logs/05_build_aterio_campus.txt
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, INTER, OUTLOGS, progress, save_table
from geo import county_list, points_to_county

SNAP = pd.Timestamp("2026-06-30")
lines = []
log = lambda s: (print(s), lines.append(str(s)))

f = pd.read_parquet(INTER / "aterio_facility.parquet")
log(f"US facilities: {len(f)}")

# ---------------------------------------------------------------- county assignment
ok = f.LOCATION_LATITUDE.notna() & f.LOCATION_LONGITUDE.notna()
f["fips_pip"] = pd.Series(pd.NA, index=f.index, dtype="string")
f.loc[ok, "fips_pip"] = points_to_county(f.loc[ok, "LOCATION_LATITUDE"].values,
                                         f.loc[ok, "LOCATION_LONGITUDE"].values).values
af = f.COUNTY_FIPS_CODE.astype("string")
valid = set(county_list())
f["fips_aterio"] = af.where(af.isin(valid)).astype("string")
f["fips"] = f.fips_pip.fillna(f.fips_aterio)
f["fips_source"] = np.where(f.fips_pip.notna(), "point-in-polygon",
                            np.where(f.fips_aterio.notna(), "aterio_fips", "none"))
both = f.fips_pip.notna() & f.fips_aterio.notna()
log(f"Coords present: {ok.sum()}; PIP assigned: {f.fips_pip.notna().sum()}; "
    f"Aterio FIPS present: {af.notna().sum()} (valid 2020 code: {f.fips_aterio.notna().sum()})")
log(f"Agreement PIP vs Aterio FIPS where both present: {(f.fips_pip[both] == f.fips_aterio[both]).mean():.4f} "
    f"({(f.fips_pip[both] != f.fips_aterio[both]).sum()} disagree of {both.sum()})")
log("Aterio FIPS not in 2020 universe: " + str(af[af.notna() & ~af.isin(valid)].value_counts().head(20).to_dict()))
log("County source:\n" + f.fips_source.value_counts().to_string())
dis = f[both & (f.fips_pip != f.fips_aterio)][["STATE_CODE", "fips_pip", "fips_aterio"]]
dis.to_csv(OUTLOGS / "05_fips_disagreements.csv", index=False)
log(f"Disagreements in same state: {(dis.fips_pip.str[:2] == dis.fips_aterio.str[:2]).mean():.3f}")

# ---------------------------------------------------------------- stage harmonization + A5
f["stage"] = f.DATA_CENTER_STAGE
f["has_cancel_date"] = f.DATA_CENTER_CANCELLED_DATE.notna().astype(int)
f["has_withdraw_date"] = f.DATA_CENTER_PROJECT_WITHDRAWN_DATE.notna().astype(int)
a5 = pd.crosstab(f.stage, [f.has_cancel_date, f.has_withdraw_date], margins=True)
a5.columns = [f"cancel_date={a}|withdraw_date={b}" if a != "All" else "All" for a, b in a5.columns]
save_table(a5.reset_index(), "a5_stage_vs_dates_facility")
log("A5 stage x (cancel date, withdrawn date) facility counts:\n" + a5.to_string())

f["is_failed"] = f.stage.isin(["Not Approved/Withdrawn", "Cancelled"]).astype(int)
f["ann_date"] = f.DATA_CENTER_ANNOUNCED_DATE
f["cs_date"] = f.DATA_CENTER_CONSTRUCTION_START_DATE.where(f.DATA_CENTER_CONSTRUCTION_START_DATE <= SNAP)
lag = (f.cs_date - f.ann_date).dt.days / 30.4375
log("Facility months announced->construction start (both present, start<=snapshot):\n"
    + lag.describe(percentiles=[.25, .5, .75, .8, .9]).round(2).to_string())
lag_tab = lag.describe(percentiles=[.1, .25, .5, .75, .8, .9]).rename("months").reset_index()
save_table(lag_tab, "a5_announce_to_construction_lag_facility")

# ---------------------------------------------------------------- campus aggregation
f["campus_id"] = f.ATERIO_DATA_CENTER_CAMPUS_UID.fillna("SOLO_" + f.ATERIO_DATA_CENTER_UID)
f["order"] = np.arange(len(f))
f = f.sort_values(["campus_id", "ann_date", "order"], na_position="last")
first = f.groupby("campus_id").head(1).set_index("campus_id")
g = f.groupby("campus_id")
RANK = {"Active": 5, "Construction": 4, "Delayed": 3, "Announcement": 2, "Land Bank": 1}


def campus_stage(s):
    live = [x for x in s if x in RANK]
    if live:
        return max(live, key=RANK.get)
    return "Cancelled" if "Cancelled" in set(s) else "Not Approved/Withdrawn"


def mode(s):
    s = s.dropna()
    return s.mode().iloc[0] if len(s) else np.nan


c = pd.DataFrame({
    "n_buildings": g.size(),
    "campus_uid_missing": g.ATERIO_DATA_CENTER_CAMPUS_UID.apply(lambda s: s.isna().all()).astype(int),
    "fips": first.fips, "fips_source": first.fips_source, "fips_aterio": first.fips_aterio,
    "state": first.STATE_CODE,
    "n_counties": g.fips.nunique(),
    "lat": first.LOCATION_LATITUDE, "lon": first.LOCATION_LONGITUDE,
    "ann_date": g.ann_date.min(),
    "n_bldg_ann_date": g.ann_date.count(),
    "constr_start": g.cs_date.min(),
    "activation_min": g.DATA_CENTER_ACTIVATION_DATE.min(),
    "record_created": g.RECORD_CREATED_DATE.min(),
    "record_updated": g.RECORD_UPDATED_DATE.max(),
    "mw": g.SELECTED_POWER_CAPACITY_MW.sum(min_count=1),
    "mw_missing_bldgs": g.SELECTED_POWER_CAPACITY_MW.apply(lambda s: s.isna().sum()),
    "ai": g.FLG_AI_FACILITY.apply(lambda s: int((s == "Y").any())),
    "btm": g.FLG_BTM_ONSITE_POWER_GENERATION.apply(lambda s: int((s == "Y").any())),
    "provider": g.PROVIDER_NAME.agg(mode),
    "provider_type": g.PROVIDER_PUBLIC_PRIVATE.agg(lambda s: mode(s.str.capitalize())),
    "undisclosed_any": g.undisclosed.max(),
    "no_end_user": g.no_end_user.min(),
    "stage_campus": g.stage.agg(campus_stage),
    "failed": g.is_failed.min(),
    "failed_any": g.is_failed.max(),
    "n_failed_bldgs": g.is_failed.sum(),
    "cancel_date": g.DATA_CENTER_CANCELLED_DATE.min(),
    "withdraw_date": g.DATA_CENTER_PROJECT_WITHDRAWN_DATE.min(),
    "likelihood": g.PROJECT_EXECUTION_LIKELIHOOD.agg(mode),
    "utility_code": first.UTILITY_CODE, "utility_name": first.UTILITY_NAME,
    "ba": first.BAL_AUTH_ABBR, "ba_sub": first.BAL_AUTH_SUBREGION_CODE,
    "permit_url_any": g.PROJECT_PERMIT_URL.apply(lambda s: int(s.notna().any())),
}).reset_index()
c["undisclosed"] = (c.provider == "Company Not Disclosed").astype(int)
c["provider_public"] = (c.provider_type == "Public").astype(float).where(c.provider_type.notna())
c["ann_year"] = c.ann_date.dt.year
c["months_since_ann"] = (SNAP - c.ann_date).dt.days / 30.4375
c["months_to_constr"] = (c.constr_start - c.ann_date).dt.days / 30.4375
c["detect_lag_m"] = (c.record_created - c.ann_date).dt.days / 30.4375
c["mw_bin"] = pd.cut(c.mw, [-np.inf, 1, 10, 50, np.inf], labels=["<=1", "1-10", "10-50", "50+"])
c["mw50"] = (c.mw > 50).astype(float).where(c.mw.notna())
c["post2021"] = (c.ann_year >= 2022).astype(float).where(c.ann_year.notna())
for X in (12, 18, 24, 36):
    eligible = c.months_since_ann > X
    st = (c.failed == 0) & c.stage_campus.isin(["Announcement", "Delayed", "Land Bank"]) & c.constr_start.isna()
    c[f"stalled_{X}"] = np.where(eligible, st.astype(float), np.nan)

log(f"\nCampuses: {len(c)}; multi-county campuses: {(c.n_counties > 1).sum()}; "
    f"no county: {c.fips.isna().sum()}")
log("Campus stage:\n" + c.stage_campus.value_counts().to_string())
log(f"failed (all bldgs): {c.failed.sum()}  failed_any: {c.failed_any.sum()}  "
    f"(differ: {(c.failed != c.failed_any).sum()})")
log(f"Campuses with announced date: {c.ann_date.notna().sum()}")
log("Campus announced year:\n" + c.ann_year.value_counts(dropna=False).sort_index().to_string())
for X in (12, 18, 24, 36):
    s = c[f"stalled_{X}"]
    log(f"stalled_{X}: eligible {s.notna().sum()}, stalled {int(s.sum())} ({s.mean():.3f})")
# campus-level A5 consistency
a5c = pd.crosstab(c.stage_campus, [c.cancel_date.notna(), c.withdraw_date.notna()], margins=True)
a5c.columns = [f"cancel_date={a}|withdraw_date={b}" if a != "All" else "All" for a, b in a5c.columns]
save_table(a5c.reset_index(), "a5_stage_vs_dates_campus")
outc = pd.DataFrame({
    "outcome": ["failed (all buildings withdrawn/cancelled)", "failed_any (any building)"]
    + [f"stalled_{X}" for X in (12, 18, 24, 36)],
    "n_defined": [c.failed.notna().sum(), c.failed_any.notna().sum()]
    + [c[f"stalled_{X}"].notna().sum() for X in (12, 18, 24, 36)],
    "n_eq_1": [c.failed.sum(), c.failed_any.sum()] + [int(c[f"stalled_{X}"].sum()) for X in (12, 18, 24, 36)],
})
outc["share"] = outc.n_eq_1 / outc.n_defined
outc_ann = c[c.ann_date.notna()]
outc["n_defined_with_ann_date"] = [outc_ann.failed.notna().sum(), outc_ann.failed_any.notna().sum()] + [
    outc_ann[f"stalled_{X}"].notna().sum() for X in (12, 18, 24, 36)]
outc["n_eq_1_with_ann_date"] = [outc_ann.failed.sum(), outc_ann.failed_any.sum()] + [
    int(outc_ann[f"stalled_{X}"].sum()) for X in (12, 18, 24, 36)]
save_table(outc, "a5_outcome_definitions_campus")
log(outc.to_string(index=False))

f.to_parquet(CLEAN / "aterio_facility_geo.parquet", index=False)
c.to_parquet(CLEAN / "aterio_campus.parquet", index=False)
(OUTLOGS / "05_build_aterio_campus.txt").write_text("\n".join(lines) + "\n")
progress(f"05 Aterio campuses built: {len(c)} campuses, {c.ann_date.notna().sum()} with announced date")
