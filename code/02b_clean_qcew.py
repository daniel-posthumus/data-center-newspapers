"""02b — Clean QCEW county annual averages: newspaper publishers and warehousing (493), 2005-2025.

Rows used: own_code 5 (private), county areas (agglvl 78 = county x 6-digit NAICS x ownership for
511110/513110; agglvl 75 = county x 3-digit for 493). Counties absent from a file have no
UI-covered establishment in that industry-year -> 0 establishments.
Area codes xx999 ("unknown/undefined county") are dropped and their establishments counted.
Connecticut is reported by planning region from 2024 -> allocated to legacy counties (geo.py).
annual_avg_estabs is published for every cell; employment/wages are suppressed when
disclosure_code == 'N' (suppression rate reported).

Output: data/clean/qcew_county_year.parquet: fips, year, q_est, q_emp (NaN if suppressed),
        q_emp_suppressed, q_wage_avg, q_wh_est, q_wh_emp
"""
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, OUTLOGS, RAW, progress, save_table
from geo import county_list, harmonize

R = RAW / "qcew"
lines = []
log = lambda s: (print(s), lines.append(str(s)))
dt = {"area_fips": str, "industry_code": str, "disclosure_code": str, "own_code": str, "agglvl_code": str}


def read_year(y: int, ind: str) -> pd.DataFrame:
    if y >= 2014:
        code = ind if ind == "493" else ("511110" if y <= 2021 else "513110")
        return pd.read_csv(R / f"api_{y}_a_{code}.csv", dtype=dt)
    with zipfile.ZipFile(R / f"{y}_annual_by_industry.zip") as z:
        code = "493" if ind == "493" else "511110"
        names = [n for n in z.namelist() if re.search(rf"annual {code} ", n)]
        assert len(names) == 1, names
        d = pd.read_csv(z.open(names[0]), dtype=dt)
        # bulk files name the column annual_avg_estabs_count; API slices call it annual_avg_estabs
        return d.rename(columns={"annual_avg_estabs_count": "annual_avg_estabs"})


out = []
for ind in ["news", "493"]:
    for y in range(2005, 2026):
        q = read_year(y, ind)
        q = q[(q.own_code.str.strip() == "5") & (q.agglvl_code.str.strip().isin(["75", "78"]))].copy()
        q["area_fips"] = q.area_fips.str.strip().str.zfill(5)
        q = q[q.area_fips.str[:2].astype(int) <= 56]
        codes = q.industry_code.str.strip().unique().tolist()
        q["year"] = y
        q["ind"] = ind
        q["codes"] = ",".join(codes)
        out.append(q[["area_fips", "year", "ind", "codes", "disclosure_code", "annual_avg_estabs",
                      "annual_avg_emplvl", "total_annual_wages"]])
q = pd.concat(out, ignore_index=True)
q["supp"] = q.disclosure_code.fillna("").str.strip().eq("N")
log("Industry codes found by year:\n" + q.groupby(["ind", "year"]).codes.first().to_string())

unk = q[q.area_fips.str[2:] == "999"]
log("Unknown-county (xx999) newspaper establishments dropped, by year:\n"
    + unk[unk.ind == "news"].groupby("year").annual_avg_estabs.sum().to_string())
q = q[q.area_fips.str[2:] != "999"]

n = q[q.ind == "news"].copy()
sr = n.groupby("year").agg(cells=("supp", "size"), share_emp_suppressed=("supp", "mean"),
                           est_total=("annual_avg_estabs", "sum"))
log("QCEW newspaper county cells: suppression rate of employment/wages:\n" + sr.round(3).to_string())
save_table(sr.reset_index(), "qcew_suppression_by_year")

res = {}
for ind, pre in [("news", "q"), ("493", "q_wh")]:
    d = q[q.ind == ind].copy()
    d["emp_obs"] = d.annual_avg_emplvl.where(~d.supp)
    d["wages_obs"] = d.total_annual_wages.where(~d.supp)
    h = harmonize(d.rename(columns={"area_fips": "fips"}), "fips",
                  count_cols=["annual_avg_estabs", "emp_obs", "wages_obs"], by=["year"])
    log(f"{ind}: harmonize dropped {len(h.attrs['dropped'])} rows: {sorted(set(h.attrs['dropped']))[:10]}")
    s = d.groupby(["area_fips", "year"]).supp.max().reset_index().rename(columns={"area_fips": "fips"})
    s = harmonize(s.assign(supp=s.supp.astype(float)), "fips", rate_cols=["supp"], by=["year"])
    h = h.merge(s, on=["fips", "year"], how="left")
    h = h.rename(columns={"annual_avg_estabs": f"{pre}_est", "emp_obs": f"{pre}_emp",
                          "wages_obs": f"{pre}_wages", "supp": f"{pre}_emp_suppressed"})
    res[ind] = h

panel = pd.MultiIndex.from_product([county_list(), range(2005, 2026)], names=["fips", "year"]).to_frame(index=False)
p = panel.merge(res["news"], on=["fips", "year"], how="left").merge(res["493"], on=["fips", "year"], how="left")
for c in ["q_est", "q_wh_est"]:
    p[c] = p[c].fillna(0.0)
p["q_wage_avg"] = p.q_wages / p.q_emp
p = p.drop(columns=["q_wages", "q_wh_wages"])
p.to_parquet(CLEAN / "qcew_county_year.parquet", index=False)
summ = p.groupby("year").agg(est_total=("q_est", "sum"), zero=("q_est", lambda s: (s == 0).sum()),
                             one=("q_est", lambda s: ((s > 0) & (s < 1.5)).sum()),
                             ge3=("q_est", lambda s: (s >= 3).sum()), wh_est=("q_wh_est", "sum"))
log("QCEW balanced panel summary (zero = no UI-covered newspaper establishment):\n" + summ.to_string())
save_table(summ.reset_index(), "qcew_panel_summary_by_year")
(OUTLOGS / "02b_clean_qcew.txt").write_text("\n".join(lines) + "\n")
progress("02b QCEW cleaned (establishment counts published for all cells; 2005-2025)")
