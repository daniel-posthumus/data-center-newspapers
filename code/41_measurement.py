"""41 — Measurement diagnostics A1 (validity vs Medill), A2 (closure events), A4 (detection bias).

A4 detection lag: RECORD_CREATED_DATE starts 2024-07-01 (database inception), so for projects announced
before then the "lag" is mechanically time-until-inception. The informative sample is campuses announced
on/after 2024-07-01; the full-sample version is reported for completeness.
A4 also uses the Feb-2026 Aterio snapshot: facilities present in June 2026 but absent in Feb 2026
whose announced date is before 2026-01-01 were added late ("late-added").
Standard errors: clustered by county (campus-level regressions).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyfixest as pf

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, INTER, OUTLOGS, progress, save_table
from regs import tidy

lines = []
log = lambda s: (print(s), lines.append(str(s)))
news = pd.read_parquet(CLEAN / "news_county_year.parquet")
cty = pd.read_parquet(CLEAN / "county_controls.parquet")
STN = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
       "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
       "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
       "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
       "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
       "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY"}

# ------------------------------------------------------------------ A1
n25 = news[news.year == 2025].merge(cty[["fips", "rucc", "metro", "rural_grp", "n_tv_full", "n_radio_full"]], on="fips")
n16 = news[news.year == 2016].merge(cty[["fips", "metro"]], on="fips")
n23 = news[news.year == 2023]
a1 = pd.DataFrame([
    ["Medill 2025 report: counties with zero local news sources", 212, "report text p.6/p.16 (press release: 213)"],
    ["Medill 2025 report: counties with one local news source", 1525, "report text p.16 (press release: 1,524)"],
    ["Medill 2025: share of news deserts predominantly rural", "almost 80%", "report p.17"],
    ["QCEW 2025: counties with 0 private newspaper establishments", int(n25.q_zero.sum()), "this study"],
    ["QCEW 2025: counties with exactly 1", int((n25.q_grp == "1").sum()), "this study"],
    ["QCEW 2025: share of zero counties that are nonmetro (RUCC 4-9)", round(1 - n25[n25.q_zero == 1].metro.mean(), 3), "this study"],
    ["QCEW 2025: zero counties with >=1 full-power TV station licensed", int(((n25.q_zero == 1) & (n25.n_tv_full > 0)).sum()), "FCC CDBS"],
    ["QCEW 2025: zero counties with >=1 full-power radio station", int(((n25.q_zero == 1) & (n25.n_radio_full > 0)).sum()), "FCC CDBS"],
    ["CBP 2016 (last uncensored): counties with 0 newspaper establishments", int(n16.c_zero.sum()), "this study"],
    ["CBP 2016: share of zero counties nonmetro", round(1 - n16[n16.c_zero == 1].metro.mean(), 3), "this study"],
    ["QCEW 2016: counties with 0", int(n16.q_zero.sum()), "this study"],
    ["CBP 2023: counties with no published 511110 cell (0, 1 or 2 establishments)", int((n23.cbp_est_raw0 == 0).sum()), "CBP censors <3"],
    ["CBP 2023: counties with >=3 establishments", int(n23.cbp_ge3.sum()), "this study"],
], columns=["measure", "value", "source / note"])
a1["value"] = a1["value"].astype(str)
save_table(a1, "a1_validity_vs_medill")
log("A1:\n" + a1.to_string(index=False))
bystate = n25.assign(st=n25.fips.str[:2].map(STN)).groupby("st").agg(
    counties=("fips", "size"), qcew_zero=("q_zero", "sum"), qcew_one=("q_grp", lambda s: (s == "1").sum()))
bystate["share_zero"] = bystate.qcew_zero / bystate.counties
bystate = bystate.sort_values("qcew_zero", ascending=False).reset_index()
save_table(bystate, "a1_qcew_zero_by_state_2025")
log("A1 QCEW-zero counties by state, 2025 (top 15):\n" + bystate.head(15).to_string(index=False))

# ------------------------------------------------------------------ A2
pn = news.merge(cty[["fips", "rural_grp"]], on="fips")
a2 = pn[pn.year >= 2006].groupby("year").agg(q_decl=("q_decl", "sum"), q_1to0=("q_1to0", "sum"),
                                             q_0to1=("q_0to1", "sum"), c_decl=("c_decl", "sum"), c_1to0=("c_1to0", "sum"))
a2.loc[a2.index > 2016, ["c_decl", "c_1to0"]] = np.nan
save_table(a2.reset_index(), "a2_closure_events_by_year", floatfmt=".0f")
log("A2 by year (QCEW; CBP through 2016):\n" + a2.to_string())
a2r = pn[pn.year >= 2006].groupby("rural_grp").agg(counties=("fips", "nunique"), q_decl=("q_decl", "sum"),
                                                   q_1to0=("q_1to0", "sum"), c_decl=("c_decl", "sum"),
                                                   c_1to0=("c_1to0", "sum"))
a2r["q_decl_per_county"] = a2r.q_decl / a2r.counties
a2r["q_1to0_per_county"] = a2r.q_1to0 / a2r.counties
save_table(a2r.reset_index(), "a2_closure_events_by_rurality")
log("A2 by rurality (sums over 2006-2025; CBP 2006-2016):\n" + a2r.to_string())
a2yr = pn[pn.year >= 2006].pivot_table(index="year", columns="rural_grp", values="q_1to0", aggfunc="sum")
save_table(a2yr.reset_index(), "a2_1to0_by_year_rurality", floatfmt=".0f")
# size of declines: establishment count in t-1 for decline events
dec = pn[(pn.q_decl == 1)]
sz = dec.q_est_l1.describe(percentiles=[.25, .5, .75, .9]).rename("q_est_t-1_at_decline").reset_index()
save_table(sz, "a2_decline_event_prior_level")
log("Prior establishment count at decline events:\n" + sz.to_string(index=False))

# ------------------------------------------------------------------ A4 detection bias
c = pd.read_parquet(CLEAN / "campus_analysis.parquet")
c["no_ann_date"] = c.ann_date.isna().astype(int)
c["mw_missing"] = c.mw.isna().astype(int)
c["q_pcq_2025"] = c.q_pcq_2025.astype("Int64")
grp = c.groupby("q_pcq_2025").agg(campuses=("campus_id", "size"), share_no_ann_date=("no_ann_date", "mean"),
                                  share_undisclosed=("undisclosed", "mean"), share_mw_missing=("mw_missing", "mean"),
                                  share_no_end_user=("no_end_user", "mean"),
                                  share_permit_url=("permit_url_any", "mean")).reset_index()
grp2 = c.groupby("q_grp_2025").agg(campuses=("campus_id", "size"), share_no_ann_date=("no_ann_date", "mean"),
                                   share_undisclosed=("undisclosed", "mean"), share_mw_missing=("mw_missing", "mean"),
                                   share_no_end_user=("no_end_user", "mean"),
                                   share_permit_url=("permit_url_any", "mean")).reset_index()
save_table(grp, "a4_missingness_by_news_quartile_2025")
save_table(grp2, "a4_missingness_by_news_group_2025")
log("A4 missingness by 2025 QCEW per-capita quartile (all campuses):\n" + grp.to_string(index=False))
log("A4 missingness by 2025 QCEW group:\n" + grp2.to_string(index=False))

# relative representation of failed vs active
c["stage3"] = np.select([c.failed == 1, c.stage_campus == "Active"], ["failed", "active"], "other")
rep = pd.crosstab(c.q_grp_2025, c.stage3)
rep["failed_per_100_active"] = 100 * rep.failed / rep.active
rep2 = pd.crosstab(c.q_pcq_2025, c.stage3)
rep2["failed_per_100_active"] = 100 * rep2.failed / rep2.active
dd_ = c[c.ann_date.notna()]
fs = dd_.groupby("q_grp_2025").agg(dated_campuses=("campus_id", "size"), failed=("failed", "sum"),
                                   failed_share=("failed", "mean")).reset_index()
fs_q = dd_.assign(q=dd_.q_pcq.astype("Int64")).groupby("q").agg(
    dated_campuses=("campus_id", "size"), failed=("failed", "sum"), failed_share=("failed", "mean")).reset_index()
save_table(fs, "a4_failed_share_dated_by_group")
save_table(fs_q, "a4_failed_share_dated_by_annyear_quartile")
log("A4 failed share among DATED campuses by 2025 group:\n" + fs.to_string(index=False)
    + "\nby announcement-year quartile:\n" + fs_q.to_string(index=False))
save_table(rep.reset_index(), "a4_failed_vs_active_by_group")
save_table(rep2.reset_index(), "a4_failed_vs_active_by_quartile")
log("A4 failed vs active by group:\n" + rep.to_string() + "\nby quartile:\n" + rep2.to_string())

# detection-lag regressions
d = c[c.ann_date.notna() & c.q_pc10k.notna()].copy()
d["post_inception"] = (d.ann_date >= "2024-07-01").astype(int)
log(f"A4 lag sample: dated campuses {len(d)}, announced on/after 2024-07-01: {d.post_inception.sum()}")
lagdesc = d.groupby("post_inception").detect_lag_m.describe()
save_table(lagdesc.reset_index(), "a4_detect_lag_describe")
log("detection lag (months) by announced before/after inception:\n" + lagdesc.to_string())
d["log_mw_f"] = d.log_mw.fillna(d.log_mw.median())
d["mw_miss"] = d.log_mw.isna().astype(int)
ctrl = "log_density + log_income + sh_65plus + sh_ba_plus + log_mw_f + mw_miss + ai + btm"
res = []
for samp, dd in [("announced >= 2024-07-01", d[d.post_inception == 1]), ("all dated", d)]:
    for x in ["q_pc10k", "q_zero"]:
        for spec, fml in [("bivariate", f"detect_lag_m ~ {x}"), ("controls", f"detect_lag_m ~ {x} + {ctrl}"),
                          ("controls + state FE + ann-month", f"detect_lag_m ~ {x} + {ctrl} | state + ann_ym")]:
            dd = dd.assign(ann_ym=dd.ann_date.dt.to_period("M").astype(str))
            m = pf.feols(fml, data=dd, vcov={"CRV1": "fips"})
            res.append(tidy(m, x, sample=samp, spec=spec, outcome="detect_lag_m"))
lagtab = pd.concat(res)
save_table(lagtab, "a4_detect_lag_regressions")
log("A4 detection-lag regressions:\n" + lagtab.to_string(index=False))

# late-added records (Feb snapshot comparison)
feb = pd.read_parquet(INTER / "aterio_feb_snapshot.parquet")
fac = pd.read_parquet(CLEAN / "aterio_facility_geo.parquet")
fac["in_feb"] = fac.ATERIO_DATA_CENTER_UID.isin(feb.ATERIO_DATA_CENTER_UID).astype(int)
fac["late_added"] = ((fac.in_feb == 0) & (fac.ann_date < "2026-01-01")).astype(int)
fac["ann_year"] = fac.ann_date.dt.year
fac = fac.merge(news[news.year == 2025][["fips", "q_pcq", "q_grp"]], on="fips", how="left")
la = fac[fac.ann_date < "2026-01-01"].groupby("q_pcq").agg(facilities=("late_added", "size"),
                                                           late_added=("late_added", "sum"),
                                                           share_late_added=("late_added", "mean")).reset_index()
save_table(la, "a4_late_added_by_quartile")
log(f"Facilities not in Feb-2026 snapshot: {(fac.in_feb == 0).sum()}; of which announced before 2026: "
    f"{fac.late_added.sum()}")
log("A4 late-added (announced <2026, absent from Feb 2026 snapshot) by 2025 quartile:\n" + la.to_string(index=False))
(OUTLOGS / "41_measurement.txt").write_text("\n".join(lines) + "\n")
progress("41 measurement diagnostics done")
