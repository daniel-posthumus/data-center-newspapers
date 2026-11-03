"""Geography helpers: harmonize any county-FIPS data to the 2020 county universe.

Standard: the 3,143 counties / county-equivalents of the 2020 Census for the 50 states + DC
(cb_2020_us_county_500k). Connecticut therefore uses its 8 LEGACY counties (09001-09015).

Crosswalk rules (documented in the memo):
  * Renames / merges (one-to-one or many-to-one; counts summed, rates pop-weighted):
      02270 Wade Hampton      -> 02158 Kusilvak        (2015 rename)
      46113 Shannon SD        -> 46102 Oglala Lakota   (2015 rename)
      51515 Bedford city VA   -> 51019 Bedford County  (2013 merge)
      02201 Prince of Wales-Outer Ketchikan -> 02198 Prince of Wales-Hyder (2008; small area
            also went to Ketchikan; ignored)
  * Splits (one-to-many; allocated by 2020 population shares of the successor counties):
      02261 Valdez-Cordova    -> 02063 Chugach, 02066 Copper River             (2019)
      02232 Skagway-Hoonah-Angoon -> 02230 Skagway, 02105 Hoonah-Angoon        (2007)
      02280 Wrangell-Petersburg   -> 02275 Wrangell, 02195 Petersburg          (2008/2013)
  * Connecticut planning regions (09110-09190, used by Census products from 2022):
      allocated to legacy counties using the Census CT town crosswalk
      (ct_cou_to_cousub_crosswalk.txt) and town populations (PEP ESTIMATESBASE2020):
      weight(region -> county) = pop of the region's towns in that county / region pop.
      Every CT town nests in exactly one region and one legacy county, so the weights are
      exact for population; for establishments they assume establishments are distributed
      like population within a planning region (an approximation; CT has few projects).
"""
from __future__ import annotations

from functools import lru_cache

import geopandas as gpd
import numpy as np
import pandas as pd

from config import RAW

RENAME = {"02270": "02158", "46113": "46102", "51515": "51019", "02201": "02198"}
SPLITS = {"02261": ["02063", "02066"], "02232": ["02230", "02105"], "02280": ["02275", "02195"]}
STATES_51 = None  # filled lazily


@lru_cache(None)
def counties_2020() -> gpd.GeoDataFrame:
    g = gpd.read_file(f"zip://{RAW / 'census_geo' / 'cb_2020_us_county_500k.zip'}")
    g = g[g.STATEFP.astype(int) <= 56].copy()  # 50 states + DC (drops 60,66,69,72,78)
    g["fips"] = g.GEOID
    return g[["fips", "STATEFP", "NAME", "ALAND", "geometry"]].reset_index(drop=True)


@lru_cache(None)
def county_list() -> tuple:
    return tuple(sorted(counties_2020().fips))


@lru_cache(None)
def _pop2020() -> pd.Series:
    p = pd.read_csv(RAW / "census_pep" / "co-est2020-alldata.csv", dtype={"STATE": str, "COUNTY": str},
                    encoding="latin-1")
    p = p[p.SUMLEV == 50]
    return pd.Series(p.POPESTIMATE2020.values, index=p.STATE + p.COUNTY)


@lru_cache(None)
def ct_weights() -> pd.DataFrame:
    """rows: region_fips, county_fips, w (share of region pop in county), w_c (share of county pop from region)."""
    cw = pd.read_csv(RAW / "census_geo" / "ct_cou_to_cousub_crosswalk.txt", sep="|", dtype=str)
    cw.columns = [c.split("\n")[0].strip().lstrip("﻿") for c in cw.columns]
    # drop footnote rows and "County subdivisions not defined" (water-only, zero population)
    cw = cw[cw.COUSUBFP.notna() & (cw.COUSUBFP != "00000")].copy()
    cw["old"] = "09" + cw.OLD_COUNTYFP
    cw["new"] = "09" + cw.NEW_COUNTYFP
    cw["cousub"] = cw.COUSUBFP
    sub = pd.read_csv(RAW / "census_pep" / "sub-est2025_9.csv", dtype=str, encoding="latin-1")
    sub = sub[sub.SUMLEV == "061"]
    sub["pop"] = sub.ESTIMATESBASE2020.astype(float)
    m = cw.merge(sub[["COUSUB", "pop"]], left_on="cousub", right_on="COUSUB", how="left")
    assert m["pop"].notna().all(), "CT town without population"
    t = m.groupby(["new", "old"], as_index=False)["pop"].sum()
    t["w"] = t["pop"] / t.groupby("new")["pop"].transform("sum")
    t["w_c"] = t["pop"] / t.groupby("old")["pop"].transform("sum")
    return t.rename(columns={"new": "region_fips", "old": "county_fips"})


def _alloc_table() -> pd.DataFrame:
    """source fips -> target fips with count weight w and target-side weight w_c."""
    rows = [(s, t, 1.0, np.nan) for s, t in RENAME.items()]
    pop = _pop2020()
    for s, ts in SPLITS.items():
        tot = sum(pop.get(t, 0) for t in ts)
        rows += [(s, t, pop.get(t, 0) / tot, 1.0) for t in ts]
    ct = ct_weights()
    rows += [(r.region_fips, r.county_fips, r.w, r.w_c) for r in ct.itertuples()]
    return pd.DataFrame(rows, columns=["src", "fips", "w", "w_c"])


def harmonize(df: pd.DataFrame, fips_col: str, count_cols=(), rate_cols=(), by=()) -> pd.DataFrame:
    """Map df (native FIPS) to 2020 counties.

    count_cols are allocated (x * w) and summed; rate_cols are averaged with target-side weights
    (for CT: share of the legacy county's population coming from each region; for renames: simple
    mean). Rows whose FIPS is already a 2020 county pass through unchanged. Rows with FIPS outside
    the universe after mapping (e.g. 'xx999' unknown-county codes) are dropped; the caller should
    report them (returned in attribute .attrs['dropped']).
    """
    by = list(by)
    d = df.copy()
    d[fips_col] = d[fips_col].astype(str).str.zfill(5)
    at = _alloc_table()
    keep = set(county_list())
    is_src = d[fips_col].isin(at.src) & ~d[fips_col].isin(keep)
    a = d[~is_src].rename(columns={fips_col: "fips"})
    b = (d[is_src].merge(at.rename(columns={"fips": "_tgt"}), left_on=fips_col, right_on="src")
         .drop(columns=[fips_col, "src"]).rename(columns={"_tgt": "fips"}))
    for c in count_cols:
        b[c] = b[c] * b["w"]
    if len(b):
        rc = list(rate_cols)
        if rc:
            b["_wc"] = b["w_c"].fillna(1.0)
            for c in rc:
                b[c] = b[c] * b["_wc"]
        agg = {c: "sum" for c in count_cols}
        agg.update({c: "sum" for c in rc})
        if rc:
            agg["_wc"] = "sum"
        b = b.groupby(["fips"] + by, as_index=False).agg(agg)
        for c in rc:
            b[c] = b[c] / b["_wc"]
        b = b.drop(columns=[c for c in ["_wc"] if c in b])
    cols = ["fips"] + by + list(count_cols) + list(rate_cols)
    out = pd.concat([a[cols], b[cols]], ignore_index=True)
    # if a target appears in both a (already 2020) and b (allocated), combine
    agg = {c: "sum" for c in count_cols}
    agg.update({c: "mean" for c in rate_cols})
    out = out.groupby(["fips"] + by, as_index=False).agg(agg) if agg else out.drop_duplicates()
    dropped = out[~out.fips.isin(keep)]
    out = out[out.fips.isin(keep)].reset_index(drop=True)
    # list of dropped FIPS (one entry per dropped row); kept as a plain list so pandas can
    # compare attrs when frames are later merged/concatenated
    out.attrs["dropped"] = dropped.fips.tolist()
    return out


def points_to_county(lat, lon) -> pd.Series:
    """Point-in-polygon county assignment (2020 counties). Returns fips (NaN if outside)."""
    g = counties_2020()
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lon, lat), crs="EPSG:4326").to_crs(g.crs)
    j = gpd.sjoin(pts, g[["fips", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated()]
    return j["fips"].reindex(pts.index)
