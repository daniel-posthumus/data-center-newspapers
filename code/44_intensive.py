"""44 — Section D: intensive margin, campus level.

Sample: campuses with a known announcement date and host county (news supply = QCEW in the
announcement year; 2026 announcements use 2025).
Outcomes: failed (all buildings withdrawn/cancelled; LPM), stalled_24 (LPM; defined only for campuses
announced > 24 months before 2026-06-30), robustness stalled_12/18/36, failed_any; and time from
announcement to construction start (Cox PH; censored at 2026-06-30; failed campuses censored at their
cancel/withdraw date if known, otherwise at the snapshot).
Regressors: q_pc10k, q_zero.
Build-up: (1) bivariate; (2) + project chars (log MW, MW-missing, AI, BTM, provider public);
(3) + county controls (demographics, RUCC, fundamentals) + project-level siting (distance to >=230kV
substation, baseline water stress, utility industrial price) where available; (4) + state x year FE;
(5) balancing authority x year FE (instead of state x year).
SE clustered by county. Place-level news supply: not constructible (see logs/data_failures.md).
Within-county comparison: counties with >=2 dated campuses announced in different years; county FE.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, OUTLOGS, progress, save_table
from regs import run_specs, wide

lines = []
log = lambda s: (print(s), lines.append(str(s)))
c = pd.read_parquet(CLEAN / "campus_analysis.parquet")
d = c[c.ann_date.notna() & c.q_est.notna()].copy()
log(f"D sample: {len(d)} dated campuses with news supply; failed = {int(d.failed.sum())}; "
    f"stalled_24 eligible = {d.stalled_24.notna().sum()} (stalled = {int(d.stalled_24.sum())})")
d["log_mw_f"] = d.log_mw.fillna(d.log_mw.median())
d["mw_miss"] = d.log_mw.isna().astype(int)
d["prov_pub"] = d.provider_public.fillna(0)
d["prov_pub_miss"] = d.provider_public.isna().astype(int)
PROJ = "log_mw_f + mw_miss + ai + btm + prov_pub + prov_pub_miss"
cc = ["log_density", "log_income", "sh_65plus", "sh_ba_plus", "rucc", "log1p_subst230", "log1p_km345",
      "log_land_value", "price_ind_cty", "bws_raw_cty"]
pc = ["dist_km_subst_230kv", "bws_raw", "price_ind_util"]
avail = [v for v in cc + pc if v in d]
log(f"controls unavailable: {sorted(set(cc + pc) - set(avail))}")
# missing-indicator approach for project-level siting controls with incomplete coverage
CTRL = []
for v in avail:
    if d[v].isna().mean() > 0.02:
        d[v + "_m"] = d[v].isna().astype(int)
        d[v] = d[v].fillna(d[v].median())
        CTRL += [v, v + "_m"]
    else:
        CTRL.append(v)
COUNTY = " + ".join(CTRL)
S = d.dropna(subset=[v for v in CTRL]).copy()
log(f"after dropping missing county controls: {len(S)} campuses")


def specs(x, y):
    return [("(1) bivariate", f"{y} ~ {x}"),
            ("(2) +project", f"{y} ~ {x} + {PROJ}"),
            ("(3) +county & siting controls", f"{y} ~ {x} + {PROJ} + {COUNTY}"),
            ("(4) state x year FE", f"{y} ~ {x} + {PROJ} + {COUNTY} | state_year"),
            ("(5) BA x year FE", f"{y} ~ {x} + {PROJ} + {COUNTY} | ba_year")]


res = []
for y in ["failed", "stalled_24", "failed_any", "stalled_12", "stalled_18", "stalled_36"]:
    for x in ["q_pc10k", "q_zero"]:
        dd = S[S[y].notna()]
        dd = dd.copy()
        dd5 = dd[dd.ba.notna() & (dd.ba != "None")]
        r1 = run_specs(specs(x, y)[:4], dd, [x], kind="ols", cluster="fips", outcome=y, regressor=x)
        r2 = run_specs(specs(x, y)[4:], dd5, [x], kind="ols", cluster="fips", outcome=y, regressor=x)
        r = pd.concat([r1, r2])
        r["mean_y"] = dd[y].mean()
        res.append(r)
        if y in ("failed", "stalled_24"):
            save_table(wide(r), f"d_{y}_{x}")
            log(f"\nD {y} (LPM; mean {dd[y].mean():.3f}; N events {int(dd[y].sum())}) on {x}:\n"
                + wide(r).to_string(index=False))
R = pd.concat(res)
save_table(R, "d_all_long")
rob = R[R.outcome.isin(["failed_any", "stalled_12", "stalled_18", "stalled_36"])]
rw = rob.pivot_table(index=["outcome", "regressor"], columns="spec", values="coef").reset_index()
save_table(rw, "d_robustness_outcomes_coef")
log("Robustness outcomes (coefficients):\n" + rob[["outcome", "regressor", "spec", "coef", "se", "p", "n"]].to_string(index=False))

# robustness: Aterio's own county FIPS instead of point-in-polygon
alt = S[S.fips_aterio.notna() & (S.fips_aterio != S.fips)]
log(f"campuses whose Aterio FIPS differs from point-in-polygon county: {len(alt)} of {len(S)}")

# ---------------------------------------------------------------- survival
try:
    from lifelines import CoxPHFitter
    sv = S.copy()
    end = pd.Timestamp("2026-06-30")
    stop = sv[["cancel_date", "withdraw_date"]].min(axis=1)
    sv["t_end"] = np.where(sv.constr_start.notna(), sv.constr_start,
                           np.where((sv.failed == 1) & stop.notna(), stop, end))
    sv["t_end"] = pd.to_datetime(sv.t_end)
    sv["dur"] = (sv.t_end - sv.ann_date).dt.days / 30.4375
    sv["event"] = sv.constr_start.notna().astype(int)
    bad = (sv.dur <= 0)
    log(f"Cox: {len(sv)} campuses; events (construction start) {sv.event.sum()}; "
        f"non-positive durations set to 0.5 month: {bad.sum()} (construction start on/before announcement)")
    sv.loc[bad, "dur"] = 0.5
    cox = []
    for x in ["q_pc10k", "q_zero"]:
        for lab, cov in [("(1) bivariate", [x]),
                         ("(2) +project", [x] + PROJ.split(" + ")),
                         ("(3) +county & siting", [x] + PROJ.split(" + ") + CTRL)]:
            dd = sv[["dur", "event"] + cov].dropna()
            dd = dd.loc[:, dd.std() > 0] if len(dd) else dd
            cph = CoxPHFitter(penalizer=0.01)
            cph.fit(dd, "dur", "event", formula=None)
            s_ = cph.summary.loc[x]
            cox.append({"regressor": x, "spec": lab, "hazard_ratio": s_["exp(coef)"], "coef": s_["coef"],
                        "se": s_["se(coef)"], "p": s_["p"], "n": len(dd), "events": int(dd.event.sum())})
        # strata by state not used (too many small strata); state-year FE not feasible in Cox here
    CX = pd.DataFrame(cox)
    save_table(CX, "d_cox_time_to_construction")
    log("Cox PH, time from announcement to construction start (HR>1 = faster start; penalizer 0.01; "
        "SEs not clustered):\n" + CX.to_string(index=False))
except Exception as e:  # noqa
    log(f"Cox model NOT RUN: {e!r}")

# ---------------------------------------------------------------- within-county
mc = S.groupby("fips").agg(n=("campus_id", "size"), years=("ann_year", "nunique"),
                           sd_pc=("q_pc10k", "std"), zero_sw=("q_zero", "nunique"))
usable = mc[(mc.n >= 2) & (mc.years >= 2)]
usable_var = usable[usable.sd_pc > 0]
wc = pd.DataFrame({"metric": ["counties with >=2 dated campuses", "... announced in >=2 different years",
                              "... with any within-county change in q_pc10k", "... with q_zero switching",
                              "campuses in usable counties", "failed campuses in usable counties"],
                   "value": [int((mc.n >= 2).sum()), len(usable), len(usable_var), int((usable.zero_sw > 1).sum()),
                             int(S.fips.isin(usable_var.index).sum()),
                             int(S[S.fips.isin(usable_var.index)].failed.sum())]})
save_table(wc, "d_within_county_counts")
log("Within-county:\n" + wc.to_string(index=False))
W = S[S.fips.isin(usable_var.index)]
wr = []
for y in ["failed", "stalled_24"]:
    for x in ["q_pc10k", "q_zero"]:
        ww = W[W[y].notna()]
        wr.append(run_specs([("county FE + year FE", f"{y} ~ {x} + {PROJ} | fips + ann_year"),
                             ("county FE", f"{y} ~ {x} + {PROJ} | fips")], ww, [x], kind="ols",
                            cluster="fips", outcome=y, regressor=x))
WR = pd.concat(wr)
save_table(WR, "d_within_county_regressions")
log("Within-county regressions:\n" + WR[["outcome", "regressor", "spec", "coef", "se", "p", "n", "note"]].to_string(index=False))
(OUTLOGS / "44_intensive.txt").write_text("\n".join(lines) + "\n")
progress("44 intensive margin done")
