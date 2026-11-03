"""40 — Assemble analysis files.

  data/clean/county_controls.parquet  one row per 2020 county: demographics, rurality, politics,
                                      governments, broadcast, grid, power price, land value, water, broadband
  data/clean/county_year_panel.parquet  county x year 2010-2026 announcements + lagged news supply
  data/clean/campus_analysis.parquet    campus-level file with news supply in the announcement year,
                                        county controls, and project-level siting controls

Every source is harmonized to 2020 counties with geo.harmonize (counts summed, rates averaged with
population-side weights for CT). Sources that do not exist (failed pulls) are skipped and logged.
News supply in the announcement year uses QCEW for 2005-2025; 2026 announcements use 2025 (flag
news_year_lagged = 1). Merge diagnostics written to output/logs/40_build_analysis_data.txt.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, OUTLOGS, progress, save_table
from geo import county_list, harmonize

lines = []
log = lambda s: (print(s), lines.append(str(s)))
U = pd.DataFrame({"fips": list(county_list())})
U["state"] = U.fips.str[:2]


def load(name):
    f = CLEAN / name
    if not f.exists():
        log(f"MISSING clean file (skipped): {name}")
        return None
    return pd.read_parquet(f)


def attach(base, df, counts=(), rates=(), label=""):
    if df is None:
        return base
    d = df.copy()
    d["fips"] = d.fips.astype(str).str.zfill(5)
    d = d[d.fips.str[:2].astype(int) <= 56]
    # some sources ship CT both as planning regions (091xx) and legacy counties (090xx); keep legacy only
    if d.fips.str.match(r"^090\d\d$").any() and d.fips.str.startswith("091").any():
        log(f"{label}: dropping {d.fips.str.startswith('091').sum()} CT planning-region rows (legacy rows present)")
        d = d[~d.fips.str.startswith("091")]
    h = harmonize(d, "fips", count_cols=list(counts), rate_cols=list(rates))
    n_in = len(d)
    m = base.merge(h, on="fips", how="left")
    cols = list(counts) + list(rates)
    log(f"{label}: rows in {n_in}, harmonized {len(h)}, dropped {len(h.attrs['dropped'])}; "
        f"2020 counties with non-missing {cols[0]}: {m[cols[0]].notna().sum()} of {len(base)}")
    return m


cty = U.copy()
acs = load("acs_county_2021.parquet")
cty = attach(cty, acs, counts=["pop_acs", "aland_sqmi"],
             rates=["med_hh_income", "sh_65plus", "sh_ba_plus", "sh_white_nh"], label="ACS 2017-21")
cty["density"] = cty.pop_acs / cty.aland_sqmi
cty["log_density"] = np.log(cty.density)
cty["log_income"] = np.log(cty.med_hh_income)

r = load("rucc_uic.parquet")
if r is not None:
    r = r.copy()
    r["fips"] = r.fips.astype(str)
    cty = cty.merge(r[["fips", "rucc", "uic", "metro", "rucc2013"]], on="fips", how="left")
    ct = cty.fips.str.startswith("09") & cty.rucc.isna()
    cty.loc[ct, "rucc"] = cty.loc[ct, "rucc2013"]
    cty.loc[ct, "metro"] = (cty.loc[ct, "rucc2013"] <= 3).astype("Int64")
    log(f"RUCC: counties with rucc {cty.rucc.notna().sum()} (CT filled from RUCC 2013: {int(ct.sum())})")
    cty["rucc"] = cty.rucc.astype(float)
    cty["metro"] = cty.metro.astype(float)
    cty["rural_grp"] = np.select([cty.rucc <= 3, cty.rucc <= 7], ["metro (1-3)", "nonmetro adj/urban (4-7)"],
                                 "rural (8-9)")
    cty.loc[cty.rucc.isna(), "rural_grp"] = np.nan

p = load("pres_county.parquet")
if p is not None:
    for y in (2016, 2020, 2024):
        py = p[p.year == y][["fips", "rep_votes", "total_votes"]]
        cty = attach(cty, py.rename(columns={"rep_votes": f"rv{y}", "total_votes": f"tv{y}"}),
                     counts=[f"rv{y}", f"tv{y}"], label=f"pres {y}")
        cty[f"rep_share_{y}"] = cty[f"rv{y}"] / cty[f"tv{y}"]
        cty = cty.drop(columns=[f"rv{y}", f"tv{y}"])

g = load("cog_county.parquet")
cty = attach(cty, g, counts=["n_general_purpose", "n_municipal", "n_township", "n_special_district"],
             label="Census of Governments")
if "n_general_purpose" in cty:
    # counties absent from the CoG unit list have no units coded to them (15005 Kalawao; NYC boroughs,
    # whose city government is coded to 36061) -> 0
    for col in ["n_general_purpose", "n_municipal", "n_township", "n_special_district"]:
        cty[col] = cty[col].fillna(0)
    cty["govs_per10k"] = 1e4 * cty.n_general_purpose / cty.pop_acs

fcc = load("fcc_county.parquet")
cty = attach(cty, fcc, counts=["n_tv_full", "n_radio_full"], label="FCC broadcast")
for c in ["n_tv_full", "n_radio_full"]:
    if c in cty:
        cty[c] = cty[c].fillna(0)  # FCC file lists counties with >=1 station

grid = load("county_grid.parquet")
if grid is not None:
    gc = [c for c in ["n_subst_230kv", "n_subst_all", "km_lines_345kv", "km_lines_230kv"] if c in grid]
    cty = attach(cty, grid, counts=gc, label="grid")
    for c in gc:
        cty[c] = cty[c].fillna(0)
    cty["log1p_subst230"] = np.log1p(cty.get("n_subst_230kv"))
    cty["log1p_km345"] = np.log1p(cty.get("km_lines_345kv"))

ep = load("county_elec_price.parquet")
if ep is not None:
    ep = ep[ep.year == ep.year.max()]
    log(f"electricity price year used: {ep.year.max()}")
    cty = attach(cty, ep[["fips", "price_ind_cty", "price_com_cty"]], rates=["price_ind_cty", "price_com_cty"],
                 label="EIA-861 county price")

lv = load("nass_landvalue.parquet")
if lv is not None:
    lv = lv[lv.year == 2022]
    cty = attach(cty, lv[["fips", "land_value_per_acre"]], rates=["land_value_per_acre"], label="NASS land value 2022")
    cty["log_land_value"] = np.log(cty.land_value_per_acre)

w = load("county_water.parquet")
cty = attach(cty, w, rates=["bws_raw_cty"], label="Aqueduct county") if w is not None else cty

bb = load("county_broadband.parquet")
if bb is not None:
    rc = [c for c in bb.columns if c not in ("fips", "vintage") and pd.api.types.is_numeric_dtype(bb[c])]
    cty = attach(cty, bb[["fips"] + rc], rates=rc, label="broadband")

cty.to_parquet(CLEAN / "county_controls.parquet", index=False)
miss = cty.isna().sum().rename("n_missing").reset_index().rename(columns={"index": "variable"})
save_table(miss, "county_controls_missingness")
log("county controls missingness:\n" + miss.to_string(index=False))

# ------------------------------------------------------------------ county-year panel
news = pd.read_parquet(CLEAN / "news_county_year.parquet")
camp = pd.read_parquet(CLEAN / "aterio_campus.parquet")
dated = camp[camp.ann_date.notna() & camp.fips.notna()].copy()
dated["ann_year"] = dated.ann_year.astype(int)
YEARS = range(2010, 2027)
log(f"dated campuses: {len(dated)}; announced before 2010 (outside panel): {(dated.ann_year < 2010).sum()}")
pan = pd.MultiIndex.from_product([county_list(), YEARS], names=["fips", "year"]).to_frame(index=False)


def counts(sub, name):
    return sub.groupby(["fips", "ann_year"]).size().rename(name).reset_index().rename(columns={"ann_year": "year"})


parts = {"n_ann": dated, "n_ann_mw50": dated[dated.mw > 50], "n_ann_le50": dated[dated.mw <= 50],
         "n_ann_ai": dated[dated.ai == 1], "n_ann_btm": dated[dated.btm == 1],
         "n_ann_undisc": dated[dated.undisclosed == 1]}
for k, sub in parts.items():
    pan = pan.merge(counts(sub, k), on=["fips", "year"], how="left")
    pan[k] = pan[k].fillna(0)
mw = dated.groupby(["fips", "ann_year"]).mw.sum().rename("mw_ann").reset_index().rename(columns={"ann_year": "year"})
pan = pan.merge(mw, on=["fips", "year"], how="left")
pan["mw_ann"] = pan.mw_ann.fillna(0)
pan["any_ann"] = (pan.n_ann > 0).astype(int)

nv = ["q_est", "q_pc10k", "q_zero", "q_grp", "q_pcq", "q_decl", "q_1to0", "c_est", "c_zero", "c_ge3", "c_pc10k",
      "pop", "q_wh_est"]
nl = news[["fips", "year"] + nv].copy()
nl["year"] = nl.year + 1  # value from t-1 attached to t
pan = pan.merge(nl.rename(columns={c: c + "_l1" for c in nv}), on=["fips", "year"], how="left")
lead = news[["fips", "year", "q_pc10k", "q_zero"]].copy()
lead["year"] = lead.year - 5
pan = pan.merge(lead.rename(columns={"q_pc10k": "q_pc10k_f5", "q_zero": "q_zero_f5"}), on=["fips", "year"], how="left")
pan["state"] = pan.fips.str[:2]
pan["state_year"] = pan.state + "_" + pan.year.astype(str)
pan = pan.merge(cty.drop(columns=["state"]), on="fips", how="left")
pan.to_parquet(CLEAN / "county_year_panel.parquet", index=False)
log(f"county-year panel: {len(pan)} rows; announcements in panel: {int(pan.n_ann.sum())}; "
    f"counties ever announcing: {pan.groupby('fips').n_ann.sum().gt(0).sum()} of {pan.fips.nunique()}")

# ------------------------------------------------------------------ campus analysis file
c = camp.copy()
c["news_year"] = np.where(c.ann_year >= 2026, 2025, c.ann_year)
c["news_year_lagged"] = (c.ann_year >= 2026).astype(int)
nn = news[["fips", "year", "q_est", "q_pc10k", "q_zero", "q_grp", "q_pcq", "c_est", "c_zero", "c_ge3", "c_pc10k"]]
c = c.merge(nn.rename(columns={"year": "news_year"}), on=["fips", "news_year"], how="left")
nn5 = news[["fips", "year", "q_pc10k", "q_zero"]].rename(columns={"year": "news_year_f5", "q_pc10k": "q_pc10k_f5",
                                                                   "q_zero": "q_zero_f5"})
c["news_year_f5"] = c.ann_year + 5
c = c.merge(nn5, on=["fips", "news_year_f5"], how="left")
# also latest-year (2025) news supply for undated campuses (descriptives only)
n25 = news[news.year == 2025][["fips", "q_est", "q_pc10k", "q_zero", "q_grp", "q_pcq"]]
c = c.merge(n25.rename(columns={k: k + "_2025" for k in n25.columns if k != "fips"}), on="fips", how="left")
c = c.merge(cty.drop(columns=["state"]), on="fips", how="left")

fac = pd.read_parquet(CLEAN / "aterio_facility_geo.parquet")[["ATERIO_DATA_CENTER_UID", "campus_id", "ann_date",
                                                               "order"]]
fac = fac.sort_values(["campus_id", "ann_date", "order"], na_position="last").groupby("campus_id").head(1)
for fname, cols in [("facility_grid.parquet", ["dist_km_subst_230kv", "dist_km_line_345kv"]),
                    ("facility_water.parquet", ["bws_raw", "bws_cat"]),
                    ("facility_elec_price.parquet", ["price_ind_util"])]:
    d = load(fname)
    if d is None:
        continue
    cols = [x for x in cols if x in d]
    fac = fac.merge(d[["ATERIO_DATA_CENTER_UID"] + cols], on="ATERIO_DATA_CENTER_UID", how="left")
    log(f"{fname}: campuses (via first building) with {cols[0]}: {fac[cols[0]].notna().sum()} of {len(fac)}")
c = c.merge(fac.drop(columns=["ATERIO_DATA_CENTER_UID", "ann_date", "order"]), on="campus_id", how="left")
# AK/HI sites are measured to the mainland grid (distances up to ~3,900 km): treat > 500 km as missing
for col in ["dist_km_subst_230kv", "dist_km_line_345kv"]:
    if col in c:
        log(f"{col}: set to missing for {(c[col] > 500).sum()} campuses with distance > 500 km (AK/HI)")
        c.loc[c[col] > 500, col] = np.nan
c["state_year"] = c.state.astype(str) + "_" + c.ann_year.astype("Int64").astype(str)
c["ba_year"] = c.ba.astype(str) + "_" + c.ann_year.astype("Int64").astype(str)
c["log_mw"] = np.log(c.mw)
c.to_parquet(CLEAN / "campus_analysis.parquet", index=False)
d = c[c.ann_date.notna()]
log(f"campus file: {len(c)} campuses; dated {len(d)}; dated with news supply {d.q_est.notna().sum()}; "
    f"dated missing county {d.fips.isna().sum()}; 2026 announcements using 2025 news: {int(d.news_year_lagged.sum())}")
(OUTLOGS / "40_build_analysis_data.txt").write_text("\n".join(lines) + "\n")
progress("40 analysis files built")
