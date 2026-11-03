"""01b — Clean CBP county files: newspaper publishers (and NAICS 493 warehousing) 2005-2023.

Key facts verified from the files themselves (see output/logs/01b_clean_cbp.txt):
  * Newspaper publishers are coded 511110 in EVERY vintage 2005-2023, including 2022-2023
    (CBP 2022/2023 county files use NAICS 2017 codes, not 513110) — verified by scanning codes.
  * From 2017 on, CBP county files omit every 6-digit cell with fewer than 3 establishments
    (minimum published est = 3; counties with a 511110 row fall from 2,589 in 2016 to 669 in 2017).
    So for 2017+ a missing row means "0, 1 or 2 establishments", not zero.
  * Employment is suppressed (emp = 0 with empflag A-M) through 2016; from 2017 emp is
    noise-infused and suppression is flagged by emp_nf == 'D'.
  * CBP 2022-2023 report Connecticut by planning region.
  * County code 999 = statewide / unallocated establishments; dropped (counted in log).

Output: data/clean/cbp_county_year.parquet on the 2020 county universe, balanced 2005-2023:
  fips, year, cbp_est (exact <=2016; >=3 values only for 2017+, else NaN), cbp_est_raw0 (0 if no row),
  cbp_censored (1 if year>=2017 and no published row), cbp_ge3 (1 if est>=3; consistent all years),
  cbp_emp, cbp_emp_suppressed, cbp_wh_est (NAICS 493, same censoring caveat)
"""
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, OUTLOGS, RAW, progress, save_table
from geo import county_list, harmonize

lines = []
log = lambda s: (print(s), lines.append(str(s)))
rows = []
code_check = []
for y in range(2005, 2024):
    with zipfile.ZipFile(RAW / "cbp" / f"cbp{y % 100:02d}co.zip") as z:
        df = pd.read_csv(z.open(z.namelist()[0]), dtype=str)
    df.columns = df.columns.str.lower()
    has_511110 = (df.naics == "511110").sum()
    has_513110 = (df.naics == "513110").sum()
    code_check.append((y, has_511110, has_513110))
    sub = df[df.naics.isin(["511110", "513110", "493///"])].copy()
    sub["fips"] = sub.fipstate.str.zfill(2) + sub.fipscty.str.zfill(3)
    sub["year"] = y
    sub["est"] = pd.to_numeric(sub.est)
    sub["emp"] = pd.to_numeric(sub.emp)
    if "empflag" in sub:
        sub["emp_supp"] = sub.empflag.notna() & (sub.empflag.str.strip() != "")
    else:
        sub["emp_supp"] = False
    if "emp_nf" in sub:
        sub["emp_supp"] = sub.emp_supp | sub.emp_nf.eq("D")
    sub["ind"] = np.where(sub.naics == "493///", "wh", "news")
    rows.append(sub[["fips", "year", "ind", "est", "emp", "emp_supp"]])

ck = pd.DataFrame(code_check, columns=["year", "rows_511110", "rows_513110"])
log("NAICS code check (county rows per code):\n" + ck.to_string(index=False))
c = pd.concat(rows)
c = c[c.fips.str[:2].astype(int) <= 56]
unalloc = c[c.fips.str[2:] == "999"]
log("Statewide-unallocated (county 999) newspaper establishments dropped, by year:\n"
    + unalloc[unalloc.ind == "news"].groupby("year").est.sum().to_string())
c = c[c.fips.str[2:] != "999"]

news = c[c.ind == "news"].copy()
mn = news.groupby("year").est.agg(["count", "sum", "min"])
mn["n_lt3"] = news.assign(l=news.est < 3).groupby("year").l.sum()
log("Published 511110 county cells by year (count, total est, min est, cells with est<3):\n" + mn.to_string())
save_table(mn.reset_index().rename(columns={"count": "county_cells", "sum": "total_est", "min": "min_est"}),
           "cbp_published_cells_by_year")

news["emp_obs"] = news.emp.where(~news.emp_supp)
supp = news.groupby("year").emp_supp.mean()
log("Share of published newspaper county cells with suppressed employment:\n" + supp.round(3).to_string())
save_table(supp.rename("share_emp_suppressed").reset_index(), "cbp_emp_suppression_by_year")

# CT 2022-2023 is by planning region; censoring (<3) is defined at the region level and cannot be
# carried to legacy counties, so CT CBP values for 2022-2023 are set to missing (QCEW covers CT).
ct_pr = news.fips.str.startswith("091") & (news.year >= 2022)
news_ct = news[ct_pr]
news = news[~ct_pr]
h = harmonize(news, "fips", count_cols=["est", "emp_obs"], by=["year"])
log(f"harmonize dropped rows: {len(h.attrs['dropped'])}")
panel = pd.MultiIndex.from_product([county_list(), range(2005, 2024)], names=["fips", "year"]).to_frame(index=False)
p = panel.merge(h, on=["fips", "year"], how="left")
p["published"] = p.est.notna()
p["cbp_est_raw0"] = p.est.fillna(0)
p["cbp_censored"] = ((p.year >= 2017) & ~p.published).astype(int)
p["cbp_est"] = np.where(p.year <= 2016, p.cbp_est_raw0, p.est)
p["cbp_ge3"] = (p.cbp_est_raw0 >= 3).astype(int)
p["cbp_emp"] = p.emp_obs
ct_mask = p.fips.str.startswith("09") & (p.year >= 2022)
for col in ["cbp_est_raw0", "cbp_est", "cbp_ge3", "cbp_censored"]:
    p.loc[ct_mask, col] = np.nan
emp_s = news.groupby(["fips", "year"]).emp_supp.max().reset_index()
p = p.merge(emp_s, on=["fips", "year"], how="left").rename(columns={"emp_supp": "cbp_emp_suppressed"})

wh = c[c.ind == "wh"]
wh = wh[~(wh.fips.str.startswith("091") & (wh.year >= 2022))]
whh = harmonize(wh, "fips", count_cols=["est"], by=["year"]).rename(columns={"est": "cbp_wh_est_pub"})
p = p.merge(whh, on=["fips", "year"], how="left")
p["cbp_wh_est"] = np.where(p.year <= 2016, p.cbp_wh_est_pub.fillna(0), p.cbp_wh_est_pub)
p.loc[ct_mask, "cbp_wh_est"] = np.nan

p = p[["fips", "year", "cbp_est", "cbp_est_raw0", "cbp_censored", "cbp_ge3", "cbp_emp",
       "cbp_emp_suppressed", "cbp_wh_est"]]
p.to_parquet(CLEAN / "cbp_county_year.parquet", index=False)
summ = p.groupby("year").agg(
    counties=("fips", "size"), est_total=("cbp_est_raw0", "sum"),
    zero_or_censored=("cbp_est_raw0", lambda s: (s == 0).sum()),
    ge3=("cbp_ge3", "sum"), censored=("cbp_censored", "sum"))
log("Balanced CBP panel summary:\n" + summ.to_string())
save_table(summ.reset_index(), "cbp_panel_summary_by_year")
(OUTLOGS / "01b_clean_cbp.txt").write_text("\n".join(lines) + "\n")
progress("01b CBP cleaned; 2017+ CBP omits cells with <3 establishments (zero flag unusable after 2016)")
