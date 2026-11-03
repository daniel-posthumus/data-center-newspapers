"""06 — A3 overlap / power: campuses announced in counties that lost a newspaper establishment
within +/-3 years of the announcement year.

Closure events (county-year t, change from t-1 to t):
  decline : QCEW private newspaper establishments fell by >= 1 (q_decl)       observable 2006-2025
  1to0    : QCEW went from >= 1 establishment to 0 (q_1to0)                    observable 2006-2025
  CBP versions (c_decl, c_1to0) observable only 2006-2016 (CBP censors <3 from 2017).
Window: event year in [ann_year-3, ann_year+3]. Because QCEW ends in 2025, windows for campuses
announced 2023+ are right-truncated; we also report the pre-only window [ann_year-3, ann_year].
Variant excluding the 2021->2022 transition (NAICS 511110->513110 series break).
Outputs: output/tables/a3_*.csv/md, output/logs/06_overlap_power.txt
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, OUTLOGS, progress, save_table

lines = []
log = lambda s: (print(s), lines.append(str(s)))
c = pd.read_parquet(CLEAN / "aterio_campus.parquet")
n = pd.read_parquet(CLEAN / "news_county_year.parquet")
c = c[c.ann_date.notna() & c.fips.notna()].copy()
c["ann_year"] = c.ann_year.astype(int)
log(f"Campuses with announced date and county: {len(c)}")

ev = n[["fips", "year", "q_decl", "q_1to0", "c_decl", "c_1to0"]]


def flag(df, var, lo, hi, drop2022=False):
    m = df[["campus_id", "fips", "ann_year"]].merge(ev[["fips", "year", var]], on="fips")
    m = m[(m.year >= m.ann_year + lo) & (m.year <= m.ann_year + hi)]
    if drop2022:
        m = m[m.year != 2022]
    hit = m.groupby("campus_id")[var].max()
    obs = m.groupby("campus_id")[var].count()
    return hit.reindex(df.campus_id).fillna(0).values, obs.reindex(df.campus_id).fillna(0).values


specs = [("q_decl", -3, 3, False), ("q_decl", -3, 0, False), ("q_decl", -3, 3, True),
         ("q_1to0", -3, 3, False), ("q_1to0", -3, 0, False), ("q_1to0", -3, 3, True),
         ("c_decl", -3, 3, False), ("c_1to0", -3, 3, False)]
names = []
for var, lo, hi, d22 in specs:
    nm = f"{var}_w{lo}_{hi}" + ("_no2022" if d22 else "")
    c[nm], c[nm + "_nobs"] = flag(c, var, lo, hi, d22)
    names.append(nm)

c["stage_grp"] = c.stage_campus.replace({"Cancelled": "Failed (withdrawn/cancelled)",
                                         "Not Approved/Withdrawn": "Failed (withdrawn/cancelled)"})
tot = pd.DataFrame({"spec": names,
                    "campuses_with_event": [int(c[nm].sum()) for nm in names],
                    "share": [c[nm].mean() for nm in names],
                    "campuses_with_any_observable_year": [int((c[nm + "_nobs"] > 0).sum()) for nm in names],
                    "distinct_counties_with_event": [c.loc[c[nm] == 1, "fips"].nunique() for nm in names]})
tot["n_campuses"] = len(c)
save_table(tot, "a3_overlap_totals")
log("A3 overlap totals:\n" + tot.to_string(index=False))

key = ["q_decl_w-3_3", "q_1to0_w-3_3", "q_decl_w-3_0", "q_1to0_w-3_0"]
by_year = c.groupby("ann_year").agg(campuses=("campus_id", "size"), **{k: (k, "sum") for k in key},
                                    failed=("failed", "sum"))
by_year["failed_and_q_decl_w-3_3"] = c[c.failed == 1].groupby("ann_year")["q_decl_w-3_3"].sum()
by_year = by_year.fillna(0).astype(int).reset_index()
save_table(by_year, "a3_overlap_by_year", floatfmt=".0f")
log("By announcement year:\n" + by_year.to_string(index=False))
by_stage = c.groupby("stage_grp").agg(campuses=("campus_id", "size"), **{k: (k, "sum") for k in key}).reset_index()
by_stage.loc[len(by_stage)] = ["Total", len(c)] + [int(c[k].sum()) for k in key]
save_table(by_stage, "a3_overlap_by_stage", floatfmt=".0f")
log("By campus stage:\n" + by_stage.to_string(index=False))

# outcome-relevant cells: failed x event
cell = pd.crosstab(c.failed, c["q_decl_w-3_3"], margins=True)
log("failed x q_decl(+/-3):\n" + cell.to_string())
cell2 = pd.crosstab(c.failed, c["q_1to0_w-3_3"], margins=True)
log("failed x q_1to0(+/-3):\n" + cell2.to_string())
cells = pd.DataFrame({
    "cell": ["failed & decline(+/-3)", "not failed & decline(+/-3)", "failed & 1->0(+/-3)", "not failed & 1->0(+/-3)",
             "stalled_24 & decline(+/-3)", "eligible for stalled_24 & decline(+/-3)"],
    "n": [int(((c.failed == 1) & (c["q_decl_w-3_3"] == 1)).sum()), int(((c.failed == 0) & (c["q_decl_w-3_3"] == 1)).sum()),
          int(((c.failed == 1) & (c["q_1to0_w-3_3"] == 1)).sum()), int(((c.failed == 0) & (c["q_1to0_w-3_3"] == 1)).sum()),
          int(((c.stalled_24 == 1) & (c["q_decl_w-3_3"] == 1)).sum()),
          int((c.stalled_24.notna() & (c["q_decl_w-3_3"] == 1)).sum())]})
save_table(cells, "a3_outcome_cells")
log(cells.to_string(index=False))
c[["campus_id"] + names].to_parquet(CLEAN / "campus_closure_window_flags.parquet", index=False)
(OUTLOGS / "06_overlap_power.txt").write_text("\n".join(lines) + "\n")
progress(f"06 A3 overlap: {int(c['q_decl_w-3_3'].sum())} of {len(c)} dated campuses in counties with a QCEW decline within +/-3y; "
         f"{int(c['q_1to0_w-3_3'].sum())} with a 1->0 transition")
