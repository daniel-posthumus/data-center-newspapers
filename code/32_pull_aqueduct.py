"""32 — WRI Aqueduct 4.0 baseline water stress (bws) at HydroBASINS level-6 sub-basins.

Source: https://files.wri.org/aqueduct/aqueduct-4-0-water-risk-data.zip
  (Aqueduct40_waterrisk_download_Y2023M07D05; ~262 MB zip, kept untouched in data/raw/aqueduct40/)
Layer used: GDB layer `baseline_annual` (polygons = sub-basin (pfaf_id) x GADM admin-1 x aquifer;
bws_* are sub-basin values, repeated across pieces of the same pfaf_id). Only gid_0 == 'USA' is read.

Outputs:
  data/clean/facility_water.parquet  (point-in-polygon; nearest piece within 5 km for points just outside)
  data/clean/county_water.parquet    (area-weighted means over county x sub-basin intersections, EPSG:5070)
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, INTER, RAW, UA, progress, today, write_source_md

CRS = "EPSG:5070"
URL = "https://files.wri.org/aqueduct/aqueduct-4-0-water-risk-data.zip"
D = RAW / "aqueduct40"
Z = D / "aqueduct-4-0-water-risk-data.zip"


def load_counties():
    f = RAW / "census_geo" / "cb_2020_us_county_500k.zip"
    if not f.exists():
        u = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip"
        r = requests.get(u, headers=UA, timeout=600); r.raise_for_status()
        f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(r.content)
    g = gpd.read_file(f"zip://{f}")
    return g[g.STATEFP.astype(int) <= 56].rename(columns={"GEOID": "fips"})[["fips", "geometry"]].to_crs(CRS)


def main():
    D.mkdir(parents=True, exist_ok=True)
    if not (Z.exists() and Z.stat().st_size > 2e8):
        with requests.get(URL, headers=UA, stream=True, timeout=1800) as r:
            r.raise_for_status()
            with open(Z, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
    write_source_md(D, f"""
# WRI Aqueduct 4.0 water risk data (baseline annual)

URL: {URL}
Accessed: {today()}
Vintage: Aqueduct 4.0, release folder Aqueduct40_waterrisk_download_Y2023M07D05 (July 2023);
baseline period per WRI technical note (Kuzma et al. 2023).
License: CC BY 4.0 (World Resources Institute).
Raw zip kept untouched. Layer used: GDB/Aq40_Y2023D07M05.gdb, layer baseline_annual.
""")
    gdb = f"/vsizip/{Z}/Aqueduct40_waterrisk_download_Y2023M07D05/GDB/Aq40_Y2023D07M05.gdb"
    # (an OGR `where` filter on gid_0 returned 0 rows on this GDB, so select USA rows by FID)
    attrs = pyogrio.read_dataframe(gdb, layer="baseline_annual", read_geometry=False,
                                   columns=["gid_0"], fid_as_index=True)
    fids = attrs.index[attrs.gid_0 == "USA"].to_numpy()
    aq = pyogrio.read_dataframe(gdb, layer="baseline_annual", fids=fids,
                                columns=["pfaf_id", "gid_0", "gid_1", "name_1", "bws_raw", "bws_score", "bws_cat", "bws_label"])
    assert (aq.gid_0 == "USA").all()
    aq = aq.to_crs(CRS)
    aq["geometry"] = aq.geometry.make_valid()
    # Codes (verified in file): No Data -> raw/score/cat = -9999; Arid & Low Water Use -> cat -1,
    # raw 1, score 5; raw is capped at 9999 for some Extremely High basins.
    for c in ("bws_raw", "bws_score", "bws_cat"):
        aq.loc[aq[c] <= -9999, c] = np.nan
    print("US pieces:", len(aq), "unique pfaf_id:", aq.pfaf_id.nunique())
    print(aq.drop_duplicates("pfaf_id").bws_label.value_counts(dropna=False))
    # check bws constant within pfaf_id
    print("pfaf with >1 bws_raw value:", (aq.groupby("pfaf_id").bws_raw.nunique() > 1).sum())

    # ---- facilities
    fac = pd.read_parquet(INTER / "aterio_facility.parquet",
                          columns=["ATERIO_DATA_CENTER_UID", "LOCATION_LATITUDE", "LOCATION_LONGITUDE"])
    F = fac.dropna(subset=["LOCATION_LATITUDE", "LOCATION_LONGITUDE"])
    F = gpd.GeoDataFrame(F[["ATERIO_DATA_CENTER_UID"]], geometry=gpd.points_from_xy(F.LOCATION_LONGITUDE, F.LOCATION_LATITUDE), crs=4326).to_crs(CRS)
    cols = ["pfaf_id", "bws_raw", "bws_score", "bws_cat", "bws_label", "geometry"]
    j = gpd.sjoin(F, aq[cols], how="left", predicate="within").drop_duplicates("ATERIO_DATA_CENTER_UID")
    j["water_join"] = np.where(j.pfaf_id.notna(), "within", None)
    miss = j[j.pfaf_id.isna()][["ATERIO_DATA_CENTER_UID", "geometry"]]
    if len(miss):
        nn = gpd.sjoin_nearest(miss, aq[cols], max_distance=5000, distance_col="d").drop_duplicates("ATERIO_DATA_CENTER_UID")
        nn["water_join"] = "nearest<=5km"
        j = pd.concat([j[j.pfaf_id.notna()], nn], ignore_index=True)
    fo = fac[["ATERIO_DATA_CENTER_UID"]].merge(
        pd.DataFrame(j)[["ATERIO_DATA_CENTER_UID", "pfaf_id", "bws_raw", "bws_score", "bws_cat", "bws_label", "water_join"]],
        how="left", on="ATERIO_DATA_CENTER_UID")
    fo["pfaf_id"] = fo.pfaf_id.astype("Int64")
    fo.to_parquet(CLEAN / "facility_water.parquet", index=False)

    # ---- counties: area-weighted
    cty = load_counties()
    ov = gpd.overlay(cty, aq[cols], how="intersection", keep_geom_type=True)
    ov["a"] = ov.geometry.area

    def wmean(g, c):
        m = g[c].notna()
        return np.average(g.loc[m, c], weights=g.loc[m, "a"]) if m.any() and g.loc[m, "a"].sum() > 0 else np.nan

    # raw ratio: exclude arid/low-use (raw=1 is a flag value there) and winsorize at 1.0
    # (>0.8 is already "Extremely High"; uncapped values up to 9999 would dominate a mean)
    ov["bws_raw_w"] = ov.bws_raw.where(ov.bws_cat >= 0).clip(upper=1.0)
    rows = []
    for fips, g in ov.groupby("fips"):
        sc = wmean(g, "bws_score")
        rows.append({"fips": fips,
                     "bws_raw_cty": wmean(g, "bws_raw_w"),
                     "bws_score_cty": sc,
                     "bws_cat_cty": np.nan if np.isnan(sc) else int(min(np.floor(sc), 4)),
                     "share_arid_lowuse": g.loc[g.bws_cat == -1, "a"].sum() / g.a.sum(),
                     "n_subbasins": g.pfaf_id.nunique()})
    co = cty[["fips"]].merge(pd.DataFrame(rows), on="fips", how="left")
    co = pd.DataFrame(co)
    co["method"] = ("area-weighted over county x Aqueduct baseline_annual pieces (EPSG:5070); "
                    "bws_raw_cty excludes arid/low-use and caps raw at 1; bws_cat_cty = WRI category of "
                    "area-weighted bws_score (arid scored 5 as in WRI)")
    co.to_parquet(CLEAN / "county_water.parquet", index=False)

    print("\n==== REPORT")
    print("facilities:", len(fo), "matched:", fo.pfaf_id.notna().sum(), fo.water_join.value_counts(dropna=False).to_dict())
    print(fo.bws_label.value_counts(dropna=False))
    print(fo[["bws_raw", "bws_score", "bws_cat"]].describe().T)
    print("counties:", len(co), "with bws_raw_cty:", co.bws_raw_cty.notna().sum())
    print(co.describe().T)
    progress(f"32_pull_aqueduct: facility_water {len(fo)} rows ({fo.pfaf_id.notna().sum()} matched); county_water {len(co)} rows")


if __name__ == "__main__":
    main()
