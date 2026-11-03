"""45 — Section E: secrecy test (P3).

undisclosed = campus provider is "Company Not Disclosed" (the only non-disclosure variant found;
see 00_profile_aterio). no_end_user = no building lists END_USER_COMPANIES.
Same build-up as D (LPM, SE clustered by county). Sample A: dated campuses (news in announcement year).
Sample B: all campuses incl. undated, news supply in 2025 (descriptive robustness).
Resolution check: facilities in both the Feb-2026 and Jun-2026 snapshots -> how many switch
CND -> named (and named -> CND), by news group.
Detection link: undisclosed vs detection lag / missing announced date.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, INTER, OUTLOGS, progress, save_table
from regs import run_specs, wide

lines = []
log = lambda s: (print(s), lines.append(str(s)))
c = pd.read_parquet(CLEAN / "campus_analysis.parquet")
news = pd.read_parquet(CLEAN / "news_county_year.parquet")
c["log_mw_f"] = c.log_mw.fillna(c.log_mw.median())
c["mw_miss"] = c.log_mw.isna().astype(int)
PROJ = "log_mw_f + mw_miss + ai + btm"  # provider public/private is undefined for undisclosed providers
cc = [v for v in ["log_density", "log_income", "sh_65plus", "sh_ba_plus", "rucc", "log1p_subst230", "log1p_km345",
                  "log_land_value", "price_ind_cty", "bws_raw_cty"] if v in c]
CTRL = []
for v in cc:
    if c[v].isna().mean() > 0.02:
        c[v + "_m"] = c[v].isna().astype(int)
        c[v] = c[v].fillna(c[v].median())
        CTRL += [v, v + "_m"]
    else:
        CTRL.append(v)
COUNTY = " + ".join(CTRL)


def specs(x, y):
    return [("(1) bivariate", f"{y} ~ {x}"),
            ("(2) +project", f"{y} ~ {x} + {PROJ}"),
            ("(3) +county controls", f"{y} ~ {x} + {PROJ} + {COUNTY}"),
            ("(4) state x year FE", f"{y} ~ {x} + {PROJ} + {COUNTY} | state_year"),
            ("(5) BA x year FE", f"{y} ~ {x} + {PROJ} + {COUNTY} | ba_year")]


d = c[c.ann_date.notna() & c.q_est.notna()].dropna(subset=CTRL).copy()
log(f"E sample A (dated): {len(d)}; undisclosed {int(d.undisclosed.sum())} ({d.undisclosed.mean():.3f}); "
    f"no_end_user {int(d.no_end_user.sum())} ({d.no_end_user.mean():.3f})")
res = []
for y in ["undisclosed", "no_end_user"]:
    for x in ["q_pc10k", "q_zero"]:
        r = pd.concat([run_specs(specs(x, y)[:4], d, [x], cluster="fips", outcome=y, regressor=x, sample="A dated"),
                       run_specs(specs(x, y)[4:], d[d.ba.notna() & (d.ba != "None")], [x], cluster="fips",
                                 outcome=y, regressor=x, sample="A dated")])
        res.append(r)
        save_table(wide(r), f"e_{y}_{x}")
        log(f"\nE {y} on {x} (sample A):\n" + wide(r).to_string(index=False))
b = c[c.q_est_2025.notna()].dropna(subset=CTRL).copy()
b["state_f"] = b.state
for y in ["undisclosed", "no_end_user"]:
    for x in ["q_pc10k_2025", "q_zero_2025"]:
        sp = [("(1) bivariate", f"{y} ~ {x}"), ("(3) +controls", f"{y} ~ {x} + {PROJ} + {COUNTY}"),
              ("(3b) +controls + state FE", f"{y} ~ {x} + {PROJ} + {COUNTY} | state_f")]
        res.append(run_specs(sp, b, [x], cluster="fips", outcome=y, regressor=x, sample="B all campuses, 2025 news"))
E = pd.concat(res)
save_table(E, "e_all_long")
log("Sample B:\n" + E[E["sample"].str.startswith("B")][["outcome", "regressor", "spec", "coef", "se", "p", "n"]].to_string(index=False))

# undisclosed share by group / state
g = d.groupby("q_grp").agg(campuses=("campus_id", "size"), undisclosed=("undisclosed", "mean"),
                           no_end_user=("no_end_user", "mean")).reset_index()
save_table(g, "e_undisclosed_by_group")
log("Undisclosed by news group (dated):\n" + g.to_string(index=False))
st = c.groupby("state").agg(campuses=("campus_id", "size"), undisclosed_n=("undisclosed", "sum"),
                            undisclosed_share=("undisclosed", "mean")).sort_values("campuses", ascending=False)
st = st.reset_index()
save_table(st, "e_undisclosed_by_state")
log("Undisclosed by state (all campuses, top 20 by count):\n" + st.head(20).to_string(index=False))

# resolution between snapshots (facility level)
feb = pd.read_parquet(INTER / "aterio_feb_snapshot.parquet")
fac = pd.read_parquet(CLEAN / "aterio_facility_geo.parquet")
m = fac.merge(feb, on="ATERIO_DATA_CENTER_UID", how="inner")
m["cnd_feb"] = (m.PROVIDER_NAME_FEB == "Company Not Disclosed").astype(int)
m["cnd_jun"] = (m.PROVIDER_NAME == "Company Not Disclosed").astype(int)
tr = pd.crosstab(m.cnd_feb, m.cnd_jun, margins=True)
tr.index = [f"Feb CND={i}" for i in tr.index]
tr.columns = [f"Jun CND={j}" for j in tr.columns]
save_table(tr.reset_index(), "e_resolution_feb_to_jun")
log("Facilities in both snapshots: CND status Feb x Jun:\n" + tr.to_string())
m = m.merge(news[news.year == 2025][["fips", "q_grp"]], on="fips", how="left")
rg = m[m.cnd_feb == 1].groupby("q_grp").agg(cnd_in_feb=("cnd_feb", "size"),
                                             resolved_by_jun=("cnd_jun", lambda s: int((s == 0).sum())))
rg["share_resolved"] = rg.resolved_by_jun / rg.cnd_in_feb
save_table(rg.reset_index(), "e_resolution_by_group")
log("Resolution by 2025 news group:\n" + rg.to_string())
rec_upd = m[(m.cnd_feb == 1) & (m.cnd_jun == 0)]
log(f"Resolved facilities: {len(rec_upd)}; with RECORD_UPDATED_DATE after 2026-02-09: "
    f"{int((rec_upd.RECORD_UPDATED_DATE > '2026-02-09').sum())}")

# detection link
dl = d[d.ann_date >= "2024-07-01"]
lk = dl.groupby("undisclosed").detect_lag_m.describe()
save_table(lk.reset_index(), "e_detect_lag_by_undisclosed")
log("Detection lag (campuses announced >= 2024-07-01) by undisclosed:\n" + lk.to_string())
rr = run_specs([("lag on undisclosed, state FE", "detect_lag_m ~ undisclosed + log_mw_f + mw_miss + ai + btm | state")],
               dl, ["undisclosed"], cluster="fips", outcome="detect_lag_m")
log(rr[["term", "coef", "se", "p", "n"]].to_string(index=False))
nd = c.assign(no_ann=c.ann_date.isna().astype(int)).groupby("undisclosed").no_ann.agg(["size", "mean"])
save_table(nd.reset_index(), "e_no_ann_date_by_undisclosed")
log("Share with no announced date by undisclosed (all campuses):\n" + nd.to_string())
save_table(pd.concat([rr]), "e_detect_lag_regression")
(OUTLOGS / "45_secrecy.txt").write_text("\n".join(lines) + "\n")
progress("45 secrecy test done")
