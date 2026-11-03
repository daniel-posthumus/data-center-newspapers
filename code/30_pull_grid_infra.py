"""30 — Electric grid infrastructure: substations + transmission lines.

Sources (checked 2026-11-03):
  * Transmission lines: HIFLD "U.S. Electric Power Transmission Lines" as hosted by
    Esri's Federal_User_Community (archived copy; "Last Data Update: 09/30/2024"),
    ArcGIS feature service
    https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/US_Electric_Power_Transmission_Lines/FeatureServer/0
    VOLTAGE is in kV, -999999 = missing; VOLT_CLASS is a binned string.
  * Substations: HIFLD's public "Electric Substations" layer is no longer publicly
    served (only partial third-party copies on ArcGIS Online, e.g. a 2018 FEMA copy
    with 47k features). EIA's Energy Atlas has no substation layer. So substations
    come from OpenStreetMap (power=substation, nodes/ways/relations) via the Overpass
    API, queried state by state. OSM `voltage` is in volts, multiple voltages
    separated by ';' -> we take the max.

Outputs: data/clean/county_grid.parquet, data/clean/facility_grid.parquet
"""
import gzip
import io
import json
import re
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, INTER, RAW, UA, log_failure, progress, today, write_source_md

CRS = "EPSG:5070"
STATES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
          "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()


# ---------------------------------------------------------------- counties
def load_counties():
    d = RAW / "census_geo"
    f = d / "cb_2020_us_county_500k.zip"
    if not f.exists():
        url = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip"
        r = requests.get(url, headers=UA, timeout=600)
        r.raise_for_status()
        d.mkdir(parents=True, exist_ok=True)
        f.write_bytes(r.content)
        if not (d / "SOURCE.md").exists():
            write_source_md(d, f"# Census cartographic boundary counties 2020\n\nURL: {url}\nAccessed: {today()}\nPublic domain (US Census Bureau).")
    g = gpd.read_file(f"zip://{f}")
    g = g[g.STATEFP.astype(int) <= 56].rename(columns={"GEOID": "fips"})[["fips", "geometry"]]
    return g.to_crs(CRS)


# ---------------------------------------------------------------- HIFLD lines
LINES_URL = ("https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
             "US_Electric_Power_Transmission_Lines/FeatureServer/0")


def get_lines():
    d = RAW / "hifld_transmission_lines"
    d.mkdir(parents=True, exist_ok=True)
    meta = requests.get(LINES_URL, params={"f": "json"}, headers=UA, timeout=60).json()
    (d / "layer_metadata.json").write_text(json.dumps(meta, indent=1))
    n = requests.get(f"{LINES_URL}/query", params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
                     headers=UA, timeout=60).json()["count"]
    step = 2000
    frames = []
    for i, off in enumerate(range(0, n, step)):
        f = d / f"lines_page_{i:03d}.geojson.gz"
        if not (f.exists() and f.stat().st_size > 1000):
            for attempt in range(5):
                try:
                    r = requests.get(f"{LINES_URL}/query", headers=UA, timeout=300, params={
                        "where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson",
                        "orderByFields": "OBJECTID_1", "resultOffset": off, "resultRecordCount": step})
                    r.raise_for_status()
                    json.loads(r.content)
                    f.write_bytes(gzip.compress(r.content))
                    break
                except Exception as e:  # noqa
                    print("retry lines", off, e)
                    time.sleep(10 * (attempt + 1))
            else:
                raise RuntimeError(f"lines page {off} failed")
        frames.append(gpd.GeoDataFrame.from_features(json.loads(gzip.decompress(f.read_bytes()))["features"], crs=4326))
    g = pd.concat(frames, ignore_index=True)
    g = gpd.GeoDataFrame(g, geometry="geometry", crs=4326).drop_duplicates("OBJECTID_1")
    write_source_md(d, f"""
# HIFLD Electric Power Transmission Lines (Esri Federal_User_Community archive copy)

Service: {LINES_URL}
Item: https://www.arcgis.com/home/item.html?id=d4090758322c4d32a4cd002ffaa0aa12
Accessed: {today()}
Vintage: item says "archived ... Last Data Update: 09/30/2024" (HIFLD-derived, U.S. Government data;
originally HIFLD Open, public domain). Features in service at access: {n}.
Raw: GeoJSON query pages (outSR=4326, all fields), each gzipped byte-for-byte.
VOLTAGE in kV; -999999 = not available. VOLT_CLASS binned string.
""")
    return g, n


# ---------------------------------------------------------------- OSM substations
OVERPASS = "https://overpass-api.de/api/interpreter"
OVERPASS_UA = {"User-Agent": "data-center-newspapers research pull (python-requests)"}  # Mozilla-style UA gets HTTP 406


def get_substations():
    d = RAW / "osm_substations"
    d.mkdir(parents=True, exist_ok=True)
    stamps = {}
    for st in STATES:
        f = d / f"substations_{st}.json"
        if not (f.exists() and f.stat().st_size > 200):
            q = (f'[out:json][timeout:600];area["ISO3166-2"="US-{st}"][admin_level=4]->.a;'
                 f'nwr["power"="substation"](area.a);out center tags;')
            for attempt in range(8):
                try:
                    r = requests.post(OVERPASS, data={"data": q}, headers=OVERPASS_UA, timeout=700)
                    if r.status_code in (429, 502, 503, 504):
                        raise RuntimeError(f"HTTP {r.status_code}")
                    r.raise_for_status()
                    js = json.loads(r.content)
                    if "remark" in js and "error" in js["remark"].lower():
                        raise RuntimeError(js["remark"][:200])
                    f.write_bytes(r.content)
                    break
                except Exception as e:  # noqa
                    print("retry", st, e, flush=True)
                    time.sleep(min(30 * 2 ** attempt, 300))
            else:
                log_failure("OSM Overpass", f"substations {st}", "Overpass failed after 8 retries")
                continue
            time.sleep(5)
        js = json.loads(f.read_bytes())
        stamps[st] = js.get("osm3s", {}).get("timestamp_osm_base")
        print(st, len(js["elements"]), flush=True)
    rows = []
    for st in STATES:
        f = d / f"substations_{st}.json"
        if not f.exists():
            continue
        for e in json.loads(f.read_bytes())["elements"]:
            c = e.get("center", e)
            if "lat" not in c:
                continue
            t = e.get("tags", {})
            rows.append({"osm_key": f"{e['type']}/{e['id']}", "state_query": st, "lat": c["lat"], "lon": c["lon"],
                         "voltage_raw": t.get("voltage"), "substation": t.get("substation"), "name": t.get("name")})
    s = pd.DataFrame(rows).drop_duplicates("osm_key")
    vals = sorted(v for v in stamps.values() if v)
    write_source_md(d, f"""
# OpenStreetMap substations (power=substation) via Overpass API

Endpoint: {OVERPASS}
Query per state: area["ISO3166-2"="US-XX"][admin_level=4]; nwr["power"="substation"]; out center tags;
Accessed: {today()}
OSM data timestamps (osm_base) range: {vals[0] if vals else '?'} .. {vals[-1] if vals else '?'}
License: (c) OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright).
Raw: one Overpass JSON response per state, untouched.
voltage tag: volts, multiple values separated by ';'.
""")
    return s, vals


def max_kv(v):
    """OSM voltage string -> max kV. Values are volts; explicit 'kV' handled."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    out = []
    for tok in re.split(r"[;,/]", str(v)):
        tok = tok.strip().lower().replace(" ", "")
        m = re.match(r"^(\d+(?:\.\d+)?)(kv|v)?$", tok)
        if not m:
            continue
        x = float(m.group(1))
        if m.group(2) == "kv":
            x *= 1000
        out.append(x)
    return max(out) / 1000 if out and max(out) > 0 else np.nan


def main():
    log_failure("HIFLD Electric Substations", "national substations layer (HIFLD Open / ArcGIS)",
                "no public HIFLD substations service found (only partial third-party AGOL copies, e.g. 2018 FEMA copy 47k pts); "
                "EIA Energy Atlas has no substation layer; used OSM power=substation via Overpass")
    cty = load_counties()
    fac = pd.read_parquet(INTER / "aterio_facility.parquet",
                          columns=["ATERIO_DATA_CENTER_UID", "LOCATION_LATITUDE", "LOCATION_LONGITUDE"])

    # ---- lines
    lines, n_lines_service = get_lines()
    v = pd.to_numeric(lines["VOLTAGE"], errors="coerce")
    v = v.where(v > 0)
    vc = lines["VOLT_CLASS"].astype(str).str.upper()
    lines["kv"] = v
    lines["ge345"] = (v >= 345) | (v.isna() & vc.isin(["345", "500", "735 AND ABOVE"]))
    lines["ge230"] = (v >= 230) | (v.isna() & vc.isin(["220-287", "345", "500", "735 AND ABOVE"]))
    print("lines voltage missing:", v.isna().sum(), "of", len(lines))
    print(lines["VOLT_CLASS"].value_counts(dropna=False))
    L = lines[lines.ge230].to_crs(CRS)[["kv", "ge345", "ge230", "geometry"]]
    L = L[~L.geometry.is_empty & L.geometry.notna()]
    ov = gpd.overlay(L, cty, how="intersection", keep_geom_type=True)
    ov["km"] = ov.geometry.length / 1000
    km345 = ov[ov.ge345].groupby("fips").km.sum().rename("km_lines_345kv")
    km230 = ov.groupby("fips").km.sum().rename("km_lines_230kv")
    tot_us_345 = L[L.ge345].geometry.length.sum() / 1000
    tot_us_230 = L.geometry.length.sum() / 1000

    # ---- substations
    s, stamps = get_substations()
    s["max_kv"] = s.voltage_raw.map(max_kv)
    S = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s.lon, s.lat), crs=4326).to_crs(CRS)
    S = gpd.sjoin(S, cty, how="left", predicate="within").drop(columns="index_right")
    S.drop(columns="geometry").to_parquet(INTER / "osm_substations_parsed.parquet", index=False)
    n_all = S.groupby("fips").size().rename("n_subst_all")
    n230 = S[S.max_kv >= 230].groupby("fips").size().rename("n_subst_230kv")
    n_unknown = S.groupby("fips").max_kv.apply(lambda x: x.isna().sum()).rename("n_subst_unknown_kv")

    src_sub = f"OSM power=substation via Overpass ({stamps[-1][:10] if stamps else today()})"
    src_line = "HIFLD transmission lines (Esri FUC archive, last update 2024-09-30)"
    grid_source = f"substations: {src_sub}; lines: {src_line}"

    out = cty[["fips"]].copy()
    for ser in (n230, n_all, n_unknown, km345, km230):
        out = out.merge(ser, left_on="fips", right_index=True, how="left")
    out = out.fillna(0)
    for c in ("n_subst_230kv", "n_subst_all", "n_subst_unknown_kv"):
        out[c] = out[c].astype(int)
    out["grid_source"] = grid_source
    out = pd.DataFrame(out)[["fips", "n_subst_230kv", "n_subst_all", "n_subst_unknown_kv",
                             "km_lines_345kv", "km_lines_230kv", "grid_source"]]
    out.to_parquet(CLEAN / "county_grid.parquet", index=False)

    # ---- facility distances
    F = fac.dropna(subset=["LOCATION_LATITUDE", "LOCATION_LONGITUDE"])
    F = gpd.GeoDataFrame(F, geometry=gpd.points_from_xy(F.LOCATION_LONGITUDE, F.LOCATION_LATITUDE), crs=4326).to_crs(CRS)
    sub230 = S[S.max_kv >= 230][["geometry"]]
    d1 = gpd.sjoin_nearest(F, sub230, distance_col="d").groupby("ATERIO_DATA_CENTER_UID").d.min() / 1000
    d2 = gpd.sjoin_nearest(F, L[L.ge345][["geometry"]], distance_col="d").groupby("ATERIO_DATA_CENTER_UID").d.min() / 1000
    fo = fac[["ATERIO_DATA_CENTER_UID"]].copy()
    fo["dist_km_subst_230kv"] = fo.ATERIO_DATA_CENTER_UID.map(d1)
    fo["dist_km_line_345kv"] = fo.ATERIO_DATA_CENTER_UID.map(d2)
    fo["grid_source"] = grid_source
    fo.to_parquet(CLEAN / "facility_grid.parquet", index=False)

    # ---- report
    print("\n==== REPORT")
    print("HIFLD line features:", len(lines), "(service count", n_lines_service, ")")
    print("lines VOLTAGE missing (-999999 or <=0):", int(v.isna().sum()))
    print(f"US total km >=345kV: {tot_us_345:,.0f}; >=230kV: {tot_us_230:,.0f}")
    print(f"county-summed km >=345: {out.km_lines_345kv.sum():,.0f}; >=230: {out.km_lines_230kv.sum():,.0f}")
    print("OSM substations (dedup):", len(S), "in a county:", S.fips.notna().sum())
    print("  unknown voltage:", int(S.max_kv.isna().sum()), " >=230kV:", int((S.max_kv >= 230).sum()),
          " >=345kV:", int((S.max_kv >= 345).sum()))
    print("  substation=* tag:", S.substation.value_counts(dropna=False).head(10).to_dict())
    print("  max_kv<1 (possible kV-coded or tiny):", int((S.max_kv < 1).sum()))
    print(out.describe().T)
    print(fo.describe().T)
    progress(f"30_pull_grid_infra: county_grid {len(out)} rows, facility_grid {len(fo)} rows; "
             f"OSM substations {len(S)} ({int((S.max_kv >= 230).sum())} >=230kV); HIFLD lines {len(lines)}")


if __name__ == "__main__":
    main()
