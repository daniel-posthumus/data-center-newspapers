"""46 — Section F: placebos and leave-one-state-out.

F1 placebo outcome: QCEW private warehousing & storage (NAICS 493) establishments, county x year 2010-2025.
   Outcomes: wh_net_new = max(est_t - est_{t-1}, 0) (PPML) and wh_any_new = 1{est_t > est_{t-1}} (LPM),
   regressed on lagged news supply with the same build-up as C (cols 2-5). SE clustered by state.
F2 placebo timing: news supply measured 5 years AFTER the outcome year (q_*_f5). County panel: only
   outcome years <= 2020 have t+5 <= 2025. Campus level: only campuses announced <= 2020.
F3 leave-one-state-out: C5 (any_ann LPM and n_ann PPML) and D4 (failed LPM, state x year FE), for
   regressors q_pc10k / q_zero; drop each state in turn; also drop VA, TX, VA+TX explicitly.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, OUTLOGS, progress, save_table
from regs import fit, run_specs, tidy, wide

lines = []
log = lambda s: (print(s), lines.append(str(s)))
pan = pd.read_parquet(CLEAN / "county_year_panel.parquet")
news = pd.read_parquet(CLEAN / "news_county_year.parquet")
have = [v for v in ["log1p_subst230", "log1p_km345", "log_land_value", "price_ind_cty", "bws_raw_cty"] if v in pan]
DEMO = "log_density + log_income + sh_65plus + sh_ba_plus + C(rucc)"
FUND = " + ".join(have)
need = ["log_density", "log_income", "sh_65plus", "sh_ba_plus", "rucc"] + have

# ---------------------------------------------------------------- F1 warehousing placebo
w = news[["fips", "year", "q_wh_est"]].sort_values(["fips", "year"])
w["d"] = w.groupby("fips").q_wh_est.diff()
w["wh_net_new"] = w.d.clip(lower=0)
w["wh_any_new"] = (w.d >= 0.5).astype(float).where(w.d.notna())
P = pan.merge(w[["fips", "year", "wh_net_new", "wh_any_new"]], on=["fips", "year"], how="inner")
P = P[P.year.between(2010, 2025)].dropna(subset=need + ["q_pc10k_l1", "wh_net_new"])
log(f"F1 sample: {len(P)} county-years; mean wh_any_new {P.wh_any_new.mean():.3f}; "
    f"mean wh_net_new {P.wh_net_new.mean():.3f}")
f1 = []
for y, kind in [("wh_net_new", "pois"), ("wh_any_new", "ols")]:
    for x in ["q_pc10k_l1", "q_zero_l1"]:
        sp = [("(2) +demog+RUCC, year FE", f"{y} ~ {x} + {DEMO} | year"),
              ("(3) +fundamentals", f"{y} ~ {x} + {DEMO} + {FUND} | year"),
              ("(4) state x year FE", f"{y} ~ {x} + {DEMO} + {FUND} | state_year"),
              ("(5) county FE + state x year FE", f"{y} ~ {x} | fips + state_year")]
        r = run_specs(sp, P, [x], kind=kind, cluster="state", outcome=y, regressor=x)
        f1.append(r)
        log(f"\nF1 {y} on {x}:\n" + wide(r).to_string(index=False))
# same sample/years for the data-center outcome, for side-by-side comparison
for y, kind in [("n_ann", "pois"), ("any_ann", "ols")]:
    for x in ["q_pc10k_l1", "q_zero_l1"]:
        sp = [("(4) state x year FE", f"{y} ~ {x} + {DEMO} + {FUND} | state_year"),
              ("(5) county FE + state x year FE", f"{y} ~ {x} | fips + state_year")]
        f1.append(run_specs(sp, P, [x], kind=kind, cluster="state", outcome=y + " (same sample 2010-2025)", regressor=x))
F1 = pd.concat(f1)
save_table(F1, "f1_warehousing_placebo")

# ---------------------------------------------------------------- F2 placebo timing
Q = pan[pan.year.between(2010, 2020)].dropna(subset=need + ["q_pc10k_f5"])
log(f"\nF2 county panel (outcome years 2010-2020, news at t+5): {len(Q)} county-years; "
    f"announcements in these years: {int(Q.n_ann.sum())}; county-years with any: {int(Q.any_ann.sum())}")
f2 = []
for x5, x1 in [("q_pc10k_f5", "q_pc10k_l1"), ("q_zero_f5", "q_zero_l1")]:
    for x in [x5, x1]:
        sp = [("(3) +fundamentals", f"any_ann ~ {x} + {DEMO} + {FUND} | year"),
              ("(4) state x year FE", f"any_ann ~ {x} + {DEMO} + {FUND} | state_year")]
        f2.append(run_specs(sp, Q, [x], kind="ols", cluster="state", outcome="any_ann (2010-2020)", regressor=x))
c = pd.read_parquet(CLEAN / "campus_analysis.parquet")
cq = c[c.ann_date.notna() & c.q_pc10k_f5.notna()]
log(f"F2 campus level: campuses announced <=2020 with news at t+5: {len(cq)}; failed among them: {int(cq.failed.sum())}")
if cq.failed.sum() >= 10:
    f2.append(run_specs([("bivariate", "failed ~ q_pc10k_f5")], cq, ["q_pc10k_f5"], cluster="fips",
                        outcome="failed", regressor="q_pc10k_f5"))
else:
    log("F2 campus-level placebo NOT RUN: fewer than 10 failed campuses announced <= 2020.")
F2 = pd.concat(f2)
save_table(F2, "f2_placebo_timing")
log("F2:\n" + F2[["outcome", "regressor", "spec", "coef", "se", "p", "n"]].to_string(index=False))

# ---------------------------------------------------------------- F3 leave-one-state-out
S = pan[pan.year.between(2010, 2026)].dropna(subset=need + ["q_pc10k_l1"])
d = c[c.ann_date.notna() & c.q_est.notna()].copy()
d["log_mw_f"] = d.log_mw.fillna(d.log_mw.median())
d["mw_miss"] = d.log_mw.isna().astype(int)
d["prov_pub"] = d.provider_public.fillna(0)
d["prov_pub_miss"] = d.provider_public.isna().astype(int)
cc = [v for v in ["log_density", "log_income", "sh_65plus", "sh_ba_plus", "rucc"] + have]
for v in cc:
    if d[v].isna().mean() > 0.02:
        d[v] = d[v].fillna(d[v].median())
d = d.dropna(subset=cc)
DCTL = "log_mw_f + mw_miss + ai + btm + prov_pub + prov_pub_miss + " + " + ".join(cc)
ST = {"51": "VA", "48": "TX"}
models = [("C5 any_ann LPM", S, "ols", "state", lambda x: f"any_ann ~ {x} | fips + state_year", "state"),
          ("C5 n_ann PPML", S, "pois", "state", lambda x: f"n_ann ~ {x} | fips + state_year", "state"),
          ("D4 failed LPM", d.assign(state=d.fips.str[:2]), "ols", "fips",
           lambda x: f"failed ~ {x} + {DCTL} | state_year", "state")]
rows = []
for name, data, kind, cl, f, stc in models:
    for xb in ["q_pc10k", "q_zero"]:
        x = xb + "_l1" if name.startswith("C5") else xb
        drops = [("none", [])] + [("VA", ["51"]), ("TX", ["48"]), ("VA+TX", ["51", "48"])]
        drops += [(f"state {s}", [s]) for s in sorted(data[stc].dropna().unique())]
        for lab, ss in drops:
            dd = data[~data[stc].isin(ss)]
            m, err = fit(f(x), dd, kind, cl)
            r = tidy(m, x) if m is not None else pd.DataFrame([dict(term=x, coef=np.nan, se=np.nan, p=np.nan, n=np.nan)])
            r["model"], r["dropped"], r["err"] = name, lab, err
            rows.append(r)
L = pd.concat(rows, ignore_index=True)
save_table(L, "f3_loso_all")
key = L[L.dropped.isin(["none", "VA", "TX", "VA+TX"])][["model", "term", "dropped", "coef", "se", "p", "n"]]
save_table(key, "f3_loso_key")
log("F3 key drops:\n" + key.to_string(index=False))
rng = L[L.dropped.str.startswith("state")].groupby(["model", "term"]).agg(
    min_coef=("coef", "min"), max_coef=("coef", "max"), share_p_lt_05=("p", lambda s: (s < 0.05).mean()),
    n_states=("coef", "count")).reset_index()
save_table(rng, "f3_loso_range")
log("F3 range over single-state drops:\n" + rng.to_string(index=False))
(OUTLOGS / "46_placebos.txt").write_text("\n".join(lines) + "\n")
progress("46 placebos + LOSO done")
