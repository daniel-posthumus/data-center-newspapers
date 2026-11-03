"""43 — Section C: extensive margin, county x year panel 2010-2026.

Outcomes: n_ann (campus announcements; PPML), any_ann (LPM), mw_ann (MW announced; PPML).
Regressors (one at a time): q_pc10k_l1 (QCEW newspaper establishments per 10k pop, t-1), q_zero_l1.
Build-up:
  (1) bivariate, no FE
  (2) + demographics (log density, log income, share 65+, share BA+) + RUCC dummies + year FE
  (3) + siting fundamentals (log1p substations>=230kV, log1p km lines>=345kV, log ag land value,
        industrial electricity price, baseline water stress)
  (4) + state x year FE (replaces year FE)
  (5) county FE + state x year FE (time-invariant controls absorbed)
Balancing-authority x year FE are not used here: BA is only observed for counties hosting an Aterio
project, so it is not defined for the county universe (it is used in D).
SEs clustered by state (county-panel rule). PPML drops counties whose outcome is always zero once county
FE are included; the number of such counties is reported.
Heterogeneity: stacked type panels (county x year x type) with news x type interactions, spec (4) and (5).
Event study (6): stacked design, see run_event_study().
2026 = Jan-Jun 2026 announcements (absorbed by year / state-year FE).
"""
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, FIGS, OUTLOGS, progress, save_table
from regs import fit, run_specs, tidy, wide

lines = []
log = lambda s: (print(s), lines.append(str(s)))
pan = pd.read_parquet(CLEAN / "county_year_panel.parquet")
pan = pan[pan.year.between(2010, 2026)].copy()
log(f"panel rows {len(pan)}, counties {pan.fips.nunique()}, years {pan.year.min()}-{pan.year.max()}")
never = pan.groupby("fips").n_ann.sum().eq(0)
log(f"counties with no announcement in any year 2010-2026: {never.sum()} of {len(never)} "
    f"({never.mean():.3f}); county-years with >=1 announcement: {int(pan.any_ann.sum())}")

DEMO = "log_density + log_income + sh_65plus + sh_ba_plus + C(rucc)"
FUND = "log1p_subst230 + log1p_km345 + log_land_value + price_ind_cty + bws_raw_cty"
have = [v for v in ["log1p_subst230", "log1p_km345", "log_land_value", "price_ind_cty", "bws_raw_cty"] if v in pan]
missing_fund = sorted(set(["log1p_subst230", "log1p_km345", "log_land_value", "price_ind_cty", "bws_raw_cty"]) - set(have))
if missing_fund:
    log(f"WARNING fundamentals not available: {missing_fund}")
FUND = " + ".join(have)
# common estimation sample across columns 1-4 for coefficient-stability comparisons
need = ["log_density", "log_income", "sh_65plus", "sh_ba_plus", "rucc"] + have + ["q_pc10k_l1", "q_zero_l1"]
S = pan.dropna(subset=need).copy()
log(f"common sample (non-missing controls): {len(S)} county-years, {S.fips.nunique()} counties "
    f"(dropped {pan.fips.nunique() - S.fips.nunique()} counties for missing controls)")


def specs(x, y):
    return [("(1) bivariate", f"{y} ~ {x}"),
            ("(2) +demog+RUCC, year FE", f"{y} ~ {x} + {DEMO} | year"),
            ("(3) +fundamentals", f"{y} ~ {x} + {DEMO} + {FUND} | year"),
            ("(4) state x year FE", f"{y} ~ {x} + {DEMO} + {FUND} | state_year"),
            ("(5) county FE + state x year FE", f"{y} ~ {x} | fips + state_year")]


allres = []
for y, kind in [("n_ann", "pois"), ("any_ann", "ols"), ("mw_ann", "pois")]:
    for x in ["q_pc10k_l1", "q_zero_l1"]:
        r = run_specs(specs(x, y), S, [x], kind=kind, cluster="state", outcome=y, regressor=x, model=kind)
        allres.append(r)
        save_table(wide(r), f"c_{y}_{x}")
        log(f"\nC {y} ({kind}) on {x}:\n" + wide(r).to_string(index=False))
C = pd.concat(allres)
save_table(C, "c_all_long")

# within-county variation available for (5)
w = S.groupby("fips").agg(sd_pc=("q_pc10k_l1", "std"), sw_zero=("q_zero_l1", lambda s: s.nunique() > 1),
                          any_ann=("any_ann", "max"))
wc = pd.DataFrame({"metric": ["counties in sample", "counties with >=1 announcement",
                              "counties whose q_zero_l1 switches 2010-2026",
                              "... of which with >=1 announcement",
                              "median within-county SD of q_pc10k_l1 (all)",
                              "median within-county SD of q_pc10k_l1 (announcing counties)"],
                   "value": [len(w), int(w.any_ann.sum()), int(w.sw_zero.sum()), int((w.sw_zero & (w.any_ann == 1)).sum()),
                             w.sd_pc.median(), w[w.any_ann == 1].sd_pc.median()]})
save_table(wc, "c5_within_county_variation")
log("C5 within-county variation:\n" + wc.to_string(index=False))

# ---------------------------------------------------------------- heterogeneity
het = []
pairs = {"mw50": ("n_ann_mw50", "n_ann_le50"), "ai": ("n_ann_ai", None), "btm": ("n_ann_btm", None)}
for name, (ya, yb) in pairs.items():
    a = S.assign(cnt=S[ya], typ=1)
    b = S.assign(cnt=S[yb] if yb else S.n_ann - S[ya], typ=0)
    st = pd.concat([a, b])
    st["fips_typ"] = st.fips + "_" + st.typ.astype(str)
    st["sy_typ"] = st.state_year + "_" + st.typ.astype(str)
    for x in ["q_pc10k_l1", "q_zero_l1"]:
        sp = [("(4) state x year x type FE", f"cnt ~ {x} + {x}:typ + {DEMO} + {FUND} | sy_typ"),
              ("(5) county x type + state x year x type FE", f"cnt ~ {x} + {x}:typ | fips_typ + sy_typ")]
        r = run_specs(sp, st, [x, f"{x}:typ"], kind="pois", cluster="state", outcome="count", regressor=x,
                      het=name)
        het.append(r)
for x in ["q_pc10k_l1", "q_zero_l1"]:
    S["post2021"] = (S.year >= 2022).astype(int)
    sp = [("(4) state x year FE", f"n_ann ~ {x} + {x}:post2021 + {DEMO} + {FUND} | state_year"),
          ("(5) county FE + state x year FE", f"n_ann ~ {x} + {x}:post2021 | fips + state_year")]
    het.append(run_specs(sp, S, [x, f"{x}:post2021"], kind="pois", cluster="state", outcome="n_ann",
                         regressor=x, het="post2021"))
H = pd.concat(het)
save_table(H[["het", "regressor", "spec", "term", "coef", "se", "p", "n", "note"]], "c_heterogeneity")
log("Heterogeneity (PPML; interaction terms show difference for type=1 / post-2021):\n"
    + H[["het", "regressor", "spec", "term", "coef", "se", "p", "n"]].to_string(index=False))


# ---------------------------------------------------------------- event study
def run_event_study(evvar, label, band_var="q_est"):
    """Stacked event study. Cohort g = year of a county's FIRST event (evvar==1) in 2008-2023 with no
    event in g-3..g-1. Controls for cohort g: counties with no event in g-3..g+3, same state, and
    same size band of q_est in g-1 (0-1 / 2 / 3-5 / 6+ establishments) -> 'not-yet/never-treated matched'.
    Window g-3..g+3; outcome any_ann; LPM with event-time x treated dummies (ref = -1),
    FE county x stack and year x stack; SE clustered by state."""
    news = pd.read_parquet(CLEAN / "news_county_year.parquet")
    ev = news.pivot(index="fips", columns="year", values=evvar)
    est = news.pivot(index="fips", columns="year", values=band_var)
    band = lambda v: pd.cut(v, [-1, 1.5, 2.5, 5.5, 1e9], labels=["0-1", "2", "3-5", "6+"])
    outc = pan.set_index(["fips", "year"]).any_ann
    stacks, info = [], []
    for g in range(2008, 2024):
        pre = ev[[y for y in range(g - 3, g) if y in ev]].fillna(0).sum(axis=1)
        trt = ev.index[(ev[g] == 1) & (pre == 0)]
        win = ev[[y for y in range(g - 3, g + 4) if y in ev]].fillna(0).sum(axis=1)
        ctl = ev.index[win == 0]
        b = band(est[g - 1])
        tdf = pd.DataFrame({"fips": trt, "treated": 1})
        cdf = pd.DataFrame({"fips": ctl, "treated": 0})
        df = pd.concat([tdf, cdf])
        df["band"] = b.reindex(df.fips).values
        df["st"] = df.fips.str[:2]
        cells = set(zip(tdf.fips.str[:2], b.reindex(tdf.fips).values))
        df = df[[(s, bb) in cells for s, bb in zip(df.st, df.band)]]
        rows = []
        for k in range(-3, 4):
            yy = g + k
            if yy < 2010 or yy > 2026:
                continue
            t = df.copy()
            t["year"] = yy
            t["k"] = k
            rows.append(t)
        if not rows:
            continue
        s_ = pd.concat(rows)
        s_["any_ann"] = outc.reindex(list(zip(s_.fips, s_.year))).values
        s_["stk"] = g
        stacks.append(s_)
        tr = s_[s_.treated == 1]
        info.append({"cohort": g, "treated_counties": len(trt), "matched_treated": tr.fips.nunique(),
                     "controls": s_[s_.treated == 0].fips.nunique(),
                     "trt_cy_ann": int(tr.any_ann.sum()),  # treated county-years with an announcement
                     "trt_cty_ann": tr.groupby("fips").any_ann.max().sum()})  # treated counties w/ any in window
    I = pd.DataFrame(info)
    save_table(I, f"c6_event_cohorts_{label}")
    log(f"\nEvent study [{label}] cohorts:\n" + I.to_string(index=False))
    D = pd.concat(stacks)
    tot_cells = int(D[D.treated == 1].any_ann.sum())
    if tot_cells < 30:
        log(f"Event study [{label}]: only {tot_cells} treated county-years with an announcement -> NOT ESTIMATED "
            "(too few treated cells to say anything).")
        return None, tot_cells
    for k in range(-3, 4):
        if k != -1:
            D[f"ev_{k + 3}"] = ((D.k == k) & (D.treated == 1)).astype(int)
    D["cs"] = D.fips + "_" + D.stk.astype(str)
    D["ys"] = D.year.astype(str) + "_" + D.stk.astype(str)
    terms = [f"ev_{k + 3}" for k in range(-3, 4) if k != -1]
    m, err = fit("any_ann ~ " + " + ".join(terms) + " | cs + ys", D, "ols", cluster="st")
    if m is None:
        log(f"event study failed: {err}")
        return None, tot_cells
    R = pd.concat([tidy(m, t, k=int(t.split("_")[1]) - 3) for t in terms])
    R = pd.concat([R, pd.DataFrame([{"term": "ref", "coef": 0, "se": 0, "p": np.nan, "n": R.n.iloc[0], "k": -1}])])
    R = R.sort_values("k")
    R["trt_cy_ann"] = tot_cells
    save_table(R, f"c6_event_study_{label}")
    log(f"Event study [{label}] (LPM any_ann; ref k=-1):\n" + R.to_string(index=False))
    fig, ax = plt.subplots(figsize=(5.5, 3.2))
    ax.axhline(0, color="#52514e", lw=0.8)
    ax.axvline(-0.5, color="#c3c2b7", lw=0.8, ls="--")
    ax.errorbar(R.k, R.coef, yerr=1.96 * R.se, fmt="o", color="#2a78d6", ms=5, capsize=3, lw=1.5)
    ax.set_xlabel("Years relative to newspaper-establishment event")
    ax.set_ylabel("Δ Pr(any campus announcement)")
    ax.set_title(f"Stacked event study: {label} (95% CI, SE clustered by state)", fontsize=9, loc="left")
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGS / f"c6_event_study_{label}.png", dpi=200)
    plt.close(fig)
    return R, tot_cells


run_event_study("q_decl", "decline")
run_event_study("q_1to0", "1to0")
(OUTLOGS / "43_extensive.txt").write_text("\n".join(lines) + "\n")
progress("43 extensive margin done")
