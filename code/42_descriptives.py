"""42 — Section B descriptives: project tabulations, tabulations by news supply, balance table,
maps, and time series.

News-supply groups for projects are measured in the campus's announcement year (QCEW; 2026 -> 2025).
Undated campuses are tabulated with 2025 news supply where noted.
Balance table: all 3,143 counties by 2025 QCEW group (zero / one / two+), plus the same restricted to
counties hosting >= 1 dated campus announced 2022+ (the sample that drives C-E).
Figures -> memo/figures/ (PNG). Palette: dataviz reference sequential blue for news supply,
orange for campuses (colorblind-safe pair; failed campuses additionally get a distinct marker shape).
"""
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, FIGS, OUTLOGS, progress, save_table
from geo import counties_2020

lines = []
log = lambda s: (print(s), lines.append(str(s)))
c = pd.read_parquet(CLEAN / "campus_analysis.parquet")
cty = pd.read_parquet(CLEAN / "county_controls.parquet")
news = pd.read_parquet(CLEAN / "news_county_year.parquet")
d = c[c.ann_date.notna() & (c.ann_year >= 2010)].copy()
d["ann_year"] = d.ann_year.astype(int)
d["stage_grp"] = d.stage_campus.replace({"Cancelled": "Failed", "Not Approved/Withdrawn": "Failed"})
d["mw_bin"] = d.mw_bin.astype(str).replace("nan", "missing")
log(f"Dated campuses 2010+: {len(d)}")

# ---------------------------------------------------------------- B1 project tabulations
t_year = pd.crosstab(d.ann_year, d.stage_grp, margins=True, margins_name="Total")
save_table(t_year.reset_index(), "b1_campuses_by_year_stage", floatfmt=".0f")
log("Campuses by announcement year x stage:\n" + t_year.to_string())
flags = d.groupby("ann_year").agg(campuses=("campus_id", "size"), ai=("ai", "sum"), btm=("btm", "sum"),
                                  undisclosed=("undisclosed", "sum"), mw50=("mw50", "sum"),
                                  mw_missing=("mw", lambda s: s.isna().sum()), total_mw=("mw", "sum"))
flags.loc["Total"] = flags.sum()
save_table(flags.reset_index(), "b1_campuses_by_year_flags", floatfmt=".0f")
log("Flags by year:\n" + flags.to_string())
t_mw = pd.crosstab(d.mw_bin, d.stage_grp, margins=True, margins_name="Total")
save_table(t_mw.reset_index(), "b1_campuses_by_mwbin_stage", floatfmt=".0f")
log("MW bin x stage:\n" + t_mw.to_string())
allc = c.copy()
allc["stage_grp"] = allc.stage_campus.replace({"Cancelled": "Failed", "Not Approved/Withdrawn": "Failed"})
allc["dated"] = np.where(allc.ann_date.notna(), "dated", "no announced date")
t_all = pd.crosstab(allc.stage_grp, allc.dated, margins=True, margins_name="Total")
save_table(t_all.reset_index(), "b1_all_campuses_stage_by_dated", floatfmt=".0f")
log("All campuses, stage x dated:\n" + t_all.to_string())


# ---------------------------------------------------------------- B2 by news supply
def bygroup(df, g):
    t = df.groupby(g).agg(campuses=("campus_id", "size"), share_failed=("failed", "mean"),
                          share_active=("stage_grp", lambda s: (s == "Active").mean()),
                          share_construction=("stage_grp", lambda s: (s == "Construction").mean()),
                          share_announcement=("stage_grp", lambda s: s.isin(["Announcement", "Delayed", "Land Bank"]).mean()),
                          share_ai=("ai", "mean"), share_btm=("btm", "mean"), share_mw50=("mw50", "mean"),
                          share_undisclosed=("undisclosed", "mean"), median_mw=("mw", "median"),
                          stalled_24=("stalled_24", "mean"), n_stalled_eligible=("stalled_24", "count"))
    return t.reset_index()


b2g = bygroup(d, "q_grp")
b2q = bygroup(d.assign(q_pcq=d.q_pcq.astype("Int64")), "q_pcq")
save_table(b2g, "b2_campuses_by_news_group")
save_table(b2q, "b2_campuses_by_news_quartile")
log("By news group (announcement year):\n" + b2g.to_string(index=False))
log("By per-capita quartile (announcement year):\n" + b2q.to_string(index=False))
yg = pd.crosstab(d.ann_year, d.q_grp)
save_table(yg.reset_index(), "b2_campuses_year_by_news_group", floatfmt=".0f")

# ---------------------------------------------------------------- B3 balance table
bal_vars = {"pop_acs": "Population (ACS 2017-21)", "density": "Density (per sq mi)",
            "med_hh_income": "Median HH income ($)", "rucc": "RUCC 2023 (1-9)", "metro": "Metro (share)",
            "sh_ba_plus": "Share BA+", "sh_65plus": "Share 65+", "n_subst_230kv": "Substations >=230kV",
            "km_lines_345kv": "km of >=345kV lines", "land_value_per_acre": "Ag land value $/acre (2022)",
            "price_ind_cty": "Industrial price (c/kWh)", "bws_raw_cty": "Baseline water stress (raw)",
            "rep_share_2020": "Rep. share 2020", "rep_share_2024": "Rep. share 2024",
            "n_general_purpose": "General-purpose govts", "govs_per10k": "Gen.-purpose govts per 10k",
            "n_tv_full": "Full-power TV stations", "n_radio_full": "Full-power radio stations"}
bal_vars = {k: v for k, v in bal_vars.items() if k in cty}
n25 = news[news.year == 2025][["fips", "q_grp", "q_est"]]
B = cty.merge(n25, on="fips")
host = set(d[d.ann_year >= 2022].fips.dropna())
B["host"] = B.fips.isin(host)


def baltab(df):
    rows = []
    for k, lab in bal_vars.items():
        r = {"variable": lab}
        for gname in ["0", "1", "2+"]:
            r[f"mean_{gname}"] = df.loc[df.q_grp == gname, k].mean()
        r["mean_all"] = df[k].mean()
        r["n_nonmissing"] = df[k].notna().sum()
        rows.append(r)
    out = pd.DataFrame(rows)
    out.loc[len(out)] = ["Counties (N)"] + [int((df.q_grp == g).sum()) for g in ["0", "1", "2+"]] + [len(df), len(df)]
    return out


bal = baltab(B)
balh = baltab(B[B.host])
save_table(bal, "b3_balance_all_counties", floatfmt=",.3f")
save_table(balh, "b3_balance_host_counties", floatfmt=",.3f")
log("BALANCE (all counties, by 2025 QCEW group):\n" + bal.to_string(index=False))
log("BALANCE (counties hosting a campus announced 2022+):\n" + balh.to_string(index=False))

# ---------------------------------------------------------------- B4 time series
ts = d.groupby("ann_year").agg(n=("campus_id", "size"), share_zero=("q_zero", "mean"))
ts50 = d[d.mw50 == 1].groupby("ann_year").agg(n_50=("campus_id", "size"), share_zero_50=("q_zero", "mean"))
cshare = news.groupby("year").q_zero.mean().rename("share_counties_zero")
popz = news.assign(pz=news["pop"] * news.q_zero).groupby("year").apply(lambda x: x.pz.sum() / x["pop"].sum()).rename(
    "share_pop_in_zero")
ts = ts.join(ts50, how="left").join(cshare, how="left").join(popz, how="left")
ts.loc[2026, ["share_counties_zero", "share_pop_in_zero"]] = ts.loc[2025, ["share_counties_zero", "share_pop_in_zero"]]
save_table(ts.reset_index(), "b4_share_announcements_zero_counties")
log("Time series:\n" + ts.to_string())

BLUE = {"0": "#cde2fb", "1": "#6da7ec", "2+": "#1c5cab"}
ORANGE, INK, INK2 = "#eb6834", "#0b0b0b", "#52514e"
plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False})

fig, ax = plt.subplots(figsize=(7, 3.6))
tsp = ts[ts.index >= 2018]
ax.plot(tsp.index, tsp.share_zero, color="#2a78d6", lw=2, marker="o", ms=4, label="All dated campuses")
ax.plot(tsp.index, tsp.share_zero_50, color=ORANGE, lw=2, marker="o", ms=4, label="Campuses > 50 MW")
ax.plot(tsp.index, tsp.share_pop_in_zero, color=INK2, lw=1.2, ls="--", label="Share of US population in zero counties")
for x, (n, n50) in tsp[["n", "n_50"]].iterrows():
    ax.annotate(f"n={int(n)}", (x, 0), xytext=(0, -14), textcoords="offset points", ha="center", fontsize=7, color=INK2)
ax.set_ylim(0, max(0.25, np.nanmax(tsp[["share_zero", "share_zero_50"]].values) * 1.15))
ax.set_ylabel("Share in counties with 0 newspaper establishments")
ax.set_title("Share of new campus announcements in zero-newspaper counties (QCEW, announcement year)",
             fontsize=9, loc="left")
ax.legend(frameon=False, fontsize=8, loc="upper left")
ax.grid(axis="y", color="#e5e4df", lw=0.6)
ax.text(1.0, -0.2, "2026 = Jan-Jun announcements, 2025 news supply. Source: Aterio (2026-06-30), BLS QCEW.",
        transform=ax.transAxes, ha="right", fontsize=7, color=INK2)
fig.tight_layout()
fig.savefig(FIGS / "b4_share_zero_timeseries.png", dpi=200)
plt.close(fig)

# ---------------------------------------------------------------- maps
g = counties_2020().merge(n25, on="fips")
pts = c[c.lat.notna()].copy()
P = gpd.GeoDataFrame(pts, geometry=gpd.points_from_xy(pts.lon, pts.lat), crs="EPSG:4326")


def draw(gsub, psub, fname, title, crs="EPSG:5070", ms=6):
    gs = gsub.to_crs(crs)
    ps = psub.to_crs(crs)
    fig, ax = plt.subplots(figsize=(8, 5.2))
    for k, col in BLUE.items():
        gs[gs.q_grp == k].plot(ax=ax, color=col, edgecolor="white", linewidth=0.15)
    ok = ps[ps.failed == 0]
    fl = ps[ps.failed == 1]
    ok.plot(ax=ax, color=ORANGE, markersize=ms, edgecolor="white", linewidth=0.3, alpha=0.9)
    fl.plot(ax=ax, color=INK, markersize=ms * 2.2, marker="x", linewidth=0.8)
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    h = [Patch(color=BLUE["0"], label="0 newspaper establishments"), Patch(color=BLUE["1"], label="1"),
         Patch(color=BLUE["2+"], label="2+"),
         Line2D([], [], marker="o", color="none", markerfacecolor=ORANGE, markeredgecolor="white", ms=6,
                label=f"Campus (n={len(ok)})"),
         Line2D([], [], marker="x", color=INK, ls="none", ms=6, label=f"Failed campus (n={len(fl)})")]
    ax.legend(handles=h, loc="lower left", frameon=False, fontsize=7)
    ax.set_title(title, fontsize=9, loc="left")
    ax.set_axis_off()
    fig.text(0.99, 0.01, "Counties: QCEW 2025 private newspaper-publisher establishments. Campuses: Aterio 2026-06-30, all stages.",
             ha="right", fontsize=6.5, color=INK2)
    fig.tight_layout()
    fig.savefig(FIGS / fname, dpi=200)
    plt.close(fig)


conus = g[~g.STATEFP.isin(["02", "15"])]
draw(conus, P[~P.state.isin(["AK", "HI"])], "b5_map_national.png",
     "Data-center campuses over county newspaper supply (contiguous US)", ms=4)
draw(g[g.STATEFP == "48"], P[P.state == "TX"], "b5_map_texas.png", "Texas", crs="EPSG:3083", ms=10)
draw(g[g.STATEFP == "51"], P[P.state == "VA"], "b5_map_virginia.png", "Virginia", crs="EPSG:3968", ms=10)
log(f"maps: campuses with coords {len(P)}; AK/HI campuses excluded from national map: {P.state.isin(['AK', 'HI']).sum()}")
(OUTLOGS / "42_descriptives.txt").write_text("\n".join(lines) + "\n")
progress("42 descriptives done")
