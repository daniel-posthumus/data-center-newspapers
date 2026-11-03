"""04 — County x year news-supply panel (2005-2025) with derived measures.

Primary count source: QCEW private newspaper-publisher establishments (published for every cell).
CBP is kept alongside: exact counts 2005-2016; from 2017 only cells with >=3 establishments.

Derived (q_ = QCEW, c_ = CBP):
  q_est, q_pc10k (establishments per 10k pop), q_zero (no establishment), q_grp (0 / 1 / 2+),
  q_pcq (within-year quartile of q_pc10k, 1 = lowest; tied counties share a rank, so all
  zero-establishment counties fall in quartile 1, which is therefore larger than 25%), q_decl (q_est fell
  vs t-1), q_1to0 (q_est_{t-1} >= 1 and q_est_t == 0), q_naics_break (2021->2022 transition,
  where 511110 -> 513110 added internet newspaper publishers), q_ct_break (CT 2023->2024, where
  QCEW switches to planning regions and counts are allocated).
  c_est (<=2016), c_zero (<=2016), c_ge3 (all years), c_decl / c_1to0 (<=2016 only).
Output: data/clean/news_county_year.parquet
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, OUTLOGS, progress, save_table

lines = []
log = lambda s: (print(s), lines.append(str(s)))

pop = pd.read_parquet(CLEAN / "pop_county_year.parquet")
q = pd.read_parquet(CLEAN / "qcew_county_year.parquet")
c = pd.read_parquet(CLEAN / "cbp_county_year.parquet")
p = pop.merge(q, on=["fips", "year"], how="left").merge(c, on=["fips", "year"], how="left")
assert len(p) == 3143 * 21, len(p)
p["state"] = p.fips.str[:2]
p = p.sort_values(["fips", "year"]).reset_index(drop=True)

nonint = p[(~p.fips.str.startswith("09")) & (p.q_est % 1 != 0)]
log(f"Non-integer QCEW establishment counts outside CT: {len(nonint)}")

p["q_pc10k"] = 1e4 * p.q_est / p["pop"]
p["q_zero"] = (p.q_est < 0.5).astype(int)
p["q_grp"] = np.select([p.q_est < 0.5, p.q_est < 1.5], ["0", "1"], "2+")
p["q_pcq"] = p.groupby("year").q_pc10k.transform(
    lambda s: (np.floor(4 * (s.rank(method="min") - 1) / len(s)) + 1).clip(1, 4).astype(int))
g = p.groupby("fips")
p["q_est_l1"] = g.q_est.shift(1)
p["q_d1"] = p.q_est - p.q_est_l1
p["q_decl"] = np.where(p.q_est_l1.isna(), np.nan, (p.q_d1 <= -0.5).astype(float))
p["q_1to0"] = np.where(p.q_est_l1.isna(), np.nan, ((p.q_est_l1 >= 0.5) & (p.q_est < 0.5)).astype(float))
p["q_0to1"] = np.where(p.q_est_l1.isna(), np.nan, ((p.q_est_l1 < 0.5) & (p.q_est >= 0.5)).astype(float))
p["q_naics_break"] = (p.year == 2022).astype(int)
p["q_ct_break"] = (p.fips.str.startswith("09") & (p.year == 2024)).astype(int)
for v in ["q_decl", "q_1to0", "q_0to1"]:
    p.loc[p.q_ct_break == 1, v] = np.nan

p["c_est"] = np.where(p.year <= 2016, p.cbp_est_raw0, np.nan)
p["c_zero"] = np.where(p.year <= 2016, (p.cbp_est_raw0 == 0).astype(float), np.nan)
p["c_ge3"] = p.cbp_ge3
p["c_pc10k"] = 1e4 * p.c_est / p["pop"]
p["c_est_l1"] = g.c_est.shift(1)
p["c_decl"] = np.where(p.c_est_l1.isna() | p.c_est.isna(), np.nan, (p.c_est < p.c_est_l1).astype(float))
p["c_1to0"] = np.where(p.c_est_l1.isna() | p.c_est.isna(), np.nan,
                       ((p.c_est_l1 >= 1) & (p.c_est == 0)).astype(float))

p.to_parquet(CLEAN / "news_county_year.parquet", index=False)

# QCEW vs CBP agreement 2005-2016
a = p[p.year <= 2016]
agree = pd.DataFrame({
    "corr_est": [a[["q_est", "c_est"]].corr().iloc[0, 1]],
    "both_zero": [((a.q_zero == 1) & (a.c_zero == 1)).sum()],
    "q_zero_only": [((a.q_zero == 1) & (a.c_zero == 0)).sum()],
    "c_zero_only": [((a.q_zero == 0) & (a.c_zero == 1)).sum()],
    "county_years": [len(a)],
})
log("QCEW vs CBP, 2005-2016 county-years:\n" + agree.to_string(index=False))
save_table(agree, "news_qcew_vs_cbp_agreement")
yy = p.groupby("year").agg(q_zero=("q_zero", "sum"), q_one=("q_grp", lambda s: (s == "1").sum()),
                           q_decl=("q_decl", "sum"), q_1to0=("q_1to0", "sum"), q_0to1=("q_0to1", "sum"),
                           c_zero=("c_zero", "sum"), c_decl=("c_decl", "sum"), c_1to0=("c_1to0", "sum"),
                           c_ge3=("c_ge3", "sum"))
log("By year:\n" + yy.to_string())
save_table(yy.reset_index(), "news_panel_by_year", floatfmt=".0f")
(OUTLOGS / "04_build_news_panel.txt").write_text("\n".join(lines) + "\n")
progress("04 news panel built (QCEW primary, CBP alongside)")
