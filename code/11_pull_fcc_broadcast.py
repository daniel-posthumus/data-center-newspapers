"""FCC full-power broadcast stations by community of license -> county counts.

Source actually used: FCC legacy CDBS public database file facility.zip
  https://transition.fcc.gov/Bureaus/MB/Databases/cdbs/facility.zip  (Last-Modified 2024-01-09)
The FCC LMS public dump (enterpriseefiling.fcc.gov/dataentry/...) returns HTTP 403 to scripted
requests, so it is not used (logged). CDBS has been frozen since ~Jan 2024 (applications moved to LMS),
so the vintage is "CDBS facility table as of 2024-01-09".

Station selection (fac_status == 'LICEN'):
  TV   : fac_service == 'DT' (full-power digital TV). Excludes DC (Class A), LD/TX/DR (LPTV,
         translators, replacement translators).
  Radio: fac_service in {'AM','FM'}. Excludes FX (FM translators), FB (boosters), FL (LPFM), AX.
Geocoding: community of license (comm_city, comm_state) -> 2020 Census Gazetteer place
  (incorporated first, then CDP) or county subdivision by normalized name; the place internal
  point is assigned to a county by point-in-polygon on cb_2020_us_county_500k; county
  subdivisions carry their county in the GEOID.
"""
from __future__ import annotations

import re
import unicodedata
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, OUTLOGS, RAW, UA, log_failure, progress, today, write_source_md  # noqa: E402

CDBS_URL = "https://transition.fcc.gov/Bureaus/MB/Databases/cdbs/facility.zip"
GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/"
COUNTY_SHP = RAW / "census_geo" / "cb_2020_us_county_500k.zip"
COLS = [
    "comm_city", "comm_state", "eeo_rpt_ind", "fac_address1", "fac_address2", "fac_callsign",
    "fac_channel", "fac_city", "fac_country", "fac_frequency", "fac_service", "fac_state",
    "fac_status_date", "fac_type", "facility_id", "lic_expiration_date", "fac_status", "fac_zip1",
    "fac_zip2", "station_type", "assoc_facility_id", "callsign_eff_date", "tsid_ntsc", "tsid_dtv",
    "digital_status", "sat_tv", "network_affil", "nielsen_dma", "tv_virtual_channel",
    "last_change_date", "end_of_record",
]


def download(url: str, dest: Path) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, headers=UA, timeout=300)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = s.upper().strip()
    s = re.sub(r"\(.*?\)", " ", s)
    s = s.replace(".", " ").replace("'", "").replace("-", " ")
    s = re.sub(r"\bST\b", "SAINT", s)
    s = re.sub(r"\bSTE\b", "SAINTE", s)
    s = re.sub(r"\bFT\b", "FORT", s)
    s = re.sub(r"\bMT\b", "MOUNT", s)
    s = re.sub(r"\bPT\b", "POINT", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


SUFFIX = re.compile(
    r"\s+(city and borough|consolidated government.*|metropolitan government.*|unified government.*|"
    r"urban county|city|town|village|borough|township|municipality|CDP|plantation|charter township|"
    r"CCD|UT|gore|grant|location|purchase|comunidad|zona urbana|municipio)$",
    re.I,
)


def strip_suffix(name: str) -> str:
    """Remove parenthetical and ONE trailing LSAD word (so 'Kansas City city' -> 'Kansas City')."""
    name = re.sub(r"\s*\(.*?\)", "", name).strip()
    return SUFFIX.sub("", name)


def main():
    d = RAW / "fcc_cdbs" / sorted(p.name for p in (RAW / "fcc_cdbs").glob("20*"))[-1] \
        if (RAW / "fcc_cdbs").exists() and any((RAW / "fcc_cdbs").glob("20*")) else RAW / "fcc_cdbs" / today()
    z = download(CDBS_URL, d / "facility.zip")
    with zipfile.ZipFile(z) as zf:
        raw = zf.read("facility.dat").decode("latin-1")
    vintage = "2024-01-09 (CDBS facility.zip Last-Modified; CDBS frozen)"
    write_source_md(
        d,
        f"""
# FCC CDBS public database — facility table
- URL: {CDBS_URL}
- Access date: {d.name}
- Vintage: {vintage}. Max last_change_date in file is early 2024.
- License: FCC public data (US government work, public domain).
- Note: LMS public dump (https://enterpriseefiling.fcc.gov/dataentry/public/tv/lmsDatabase.html) returned HTTP 403 to scripted requests.
- Column names from CDBS facility table documentation (31 fields + trailing '^').
""",
    )
    lines_raw = [ln.split("|") for ln in raw.splitlines() if ln.strip()]
    fac = pd.DataFrame([ln[: len(COLS)] for ln in lines_raw], columns=COLS)
    gaz_dir = RAW / "census_gazetteer" / "2020"
    for f in ("2020_Gaz_place_national.zip", "2020_Gaz_cousubs_national.zip"):
        zp = download(GAZ + f, gaz_dir / f)
        with zipfile.ZipFile(zp) as zf:
            zf.extractall(gaz_dir)
    write_source_md(gaz_dir, f"# Census 2020 Gazetteer place + county subdivision files\n- URL: {GAZ}\n- Access date: {today()}\n- Public domain (US Census Bureau).")

    lic = fac[fac["fac_status"].eq("LICEN")].copy()
    lic["service_group"] = lic["fac_service"].map({"DT": "tv_full", "AM": "am", "FM": "fm"})
    excl = lic[lic["service_group"].isna()]["fac_service"].value_counts()
    st = lic[lic["service_group"].notna()].copy()

    # --- gazetteer lookup tables
    pl = pd.read_csv(gaz_dir / "2020_Gaz_place_national.txt", sep="\t", dtype=str)
    pl.columns = pl.columns.str.strip()
    cs = pd.read_csv(gaz_dir / "2020_Gaz_cousubs_national.txt", sep="\t", dtype=str)
    cs.columns = cs.columns.str.strip()
    cty = gpd.read_file(f"zip://{COUNTY_SHP}")[["GEOID", "geometry"]].rename(columns={"GEOID": "fips"})
    pts = gpd.GeoDataFrame(
        pl, geometry=gpd.points_from_xy(pl["INTPTLONG"].astype(float), pl["INTPTLAT"].astype(float)), crs="EPSG:4269"
    ).to_crs(cty.crs)
    j = gpd.sjoin(pts, cty, how="left", predicate="within").drop(columns=["index_right"])
    j = j[~j.index.duplicated()]
    # internal points in water (e.g. San Francisco, Monterey) -> nearest county polygon
    nomatch = j["fips"].isna()
    if nomatch.any():
        near = gpd.sjoin_nearest(pts.loc[nomatch].to_crs(5070), cty.to_crs(5070), how="left")
        near = near[~near.index.duplicated()]
        j.loc[nomatch, "fips"] = near["fips"]
    pl = pd.DataFrame(j.drop(columns="geometry"))
    # manual override: New York city's internal point falls in Kings County; FCC "NEW YORK, NY"
    # community of license is conventionally Manhattan (New York County).
    pl.loc[pl["GEOID"].eq("3651000"), "fips"] = "36061"
    pl["key"] = pl["NAME"].map(lambda x: norm(strip_suffix(x)))
    pl["rank"] = (pl["LSAD"].eq("57")).astype(int)  # 0 = incorporated, 1 = CDP
    # aliases for consolidated/hyphenated names, e.g. 'Nashville-Davidson' -> 'NASHVILLE' (lower priority)
    alias = pl[pl["NAME"].str.contains("-")].copy()
    alias["key"] = alias["NAME"].map(lambda x: norm(strip_suffix(x).split("-")[0]))
    alias["rank"] = alias["rank"] + 2
    alias2 = pl[pl["key"].str.endswith(" CITY")].copy()  # 'Boise City' -> 'BOISE'
    alias2["key"] = alias2["key"].str[:-5]
    alias2["rank"] = alias2["rank"] + 2
    pl = pd.concat([pl, alias, alias2], ignore_index=True)
    pl["ALAND"] = pl["ALAND"].astype(float)
    pl = pl.sort_values(["USPS", "key", "rank", "ALAND"], ascending=[True, True, True, False])
    pl_lu = pl.drop_duplicates(["USPS", "key"])[["USPS", "key", "fips", "GEOID", "NAME"]]
    cs["key"] = cs["NAME"].map(lambda x: norm(strip_suffix(x)))
    cs["fips"] = cs["GEOID"].str[:5]
    cs["ALAND"] = cs["ALAND"].astype(float)
    cs = cs.sort_values("ALAND", ascending=False)
    cs_lu = cs.drop_duplicates(["USPS", "key"])[["USPS", "key", "fips", "GEOID", "NAME"]]

    st["key"] = st["comm_city"].map(norm)
    m1 = st.merge(pl_lu, left_on=["comm_state", "key"], right_on=["USPS", "key"], how="left")
    m1["match"] = m1["fips"].notna().map({True: "place", False: None})
    miss = m1["fips"].isna()
    m2 = m1.loc[miss, COLS + ["service_group", "key"]].merge(
        cs_lu, left_on=["comm_state", "key"], right_on=["USPS", "key"], how="left"
    )
    m1.loc[miss, ["fips", "GEOID", "NAME"]] = m2[["fips", "GEOID", "NAME"]].values
    m1.loc[miss & m1["fips"].notna(), "match"] = "cousub"
    stations = m1.drop(columns=["USPS", "end_of_record"]).rename(columns={"GEOID": "census_geoid", "NAME": "census_name"})
    stations["vintage"] = vintage
    stations.to_parquet(CLEAN / "fcc_stations.parquet", index=False)

    ok = stations[stations["fips"].notna()]
    cnt = ok.pivot_table(index="fips", columns="service_group", values="facility_id", aggfunc="nunique", fill_value=0)
    for c in ("tv_full", "am", "fm"):
        if c not in cnt:
            cnt[c] = 0
    cnt = cnt.rename(columns={"tv_full": "n_tv_full", "am": "n_am", "fm": "n_fm"}).reset_index()
    cnt["n_radio_full"] = cnt["n_am"] + cnt["n_fm"]
    allc = cty[["fips"]].drop_duplicates()
    cnt = allc.merge(cnt, on="fips", how="left").fillna(0)
    for c in ("n_tv_full", "n_am", "n_fm", "n_radio_full"):
        cnt[c] = cnt[c].astype(int)
    cnt["vintage"] = vintage
    cnt[["fips", "n_tv_full", "n_am", "n_fm", "n_radio_full", "vintage"]].to_parquet(CLEAN / "fcc_county.parquet", index=False)

    us_states = set(pl["USPS"])
    out = [f"FCC CDBS facility pull {today()} (vintage {vintage})", f"facility rows: {len(fac)}; LICEN: {len(lic)}"]
    out.append(f"kept LICEN full-power: {st['service_group'].value_counts().to_dict()}")
    out.append(f"excluded LICEN services: {excl.to_dict()}")
    out.append(f"kept stations in states/DC/PR covered by gazetteer: {stations['comm_state'].isin(us_states).sum()} of {len(stations)}")
    mr = stations.groupby("service_group")["fips"].apply(lambda s: s.notna().mean())
    out.append(f"county match rate overall: {stations['fips'].notna().mean():.4f}; by service: {mr.round(4).to_dict()}")
    out.append(f"match type: {stations['match'].value_counts(dropna=False).to_dict()}")
    um = stations[stations["fips"].isna()]
    out.append("unmatched examples: " + "; ".join((um["comm_city"] + ", " + um["comm_state"]).head(40)))
    out.append(f"counties (cb_2020 incl. PR/territories): {len(cnt)}; with >=1 full-power TV: {(cnt.n_tv_full>0).sum()}; >=1 full radio: {(cnt.n_radio_full>0).sum()}")
    out.append(f"totals mapped: TV {cnt.n_tv_full.sum()}, AM {cnt.n_am.sum()}, FM {cnt.n_fm.sum()}")
    (OUTLOGS / "11_pull_fcc_broadcast.txt").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    progress("11_pull_fcc_broadcast: CDBS facility (2024-01 vintage) -> fcc_stations/fcc_county parquet")


if __name__ == "__main__":
    log_failure("FCC LMS public database", "enterpriseefiling.fcc.gov LMS dump/page", "HTTP 403 to scripted requests; used frozen CDBS facility.zip (2024-01-09) instead")
    main()
