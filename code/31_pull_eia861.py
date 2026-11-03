"""31 — EIA-861 utility retail sales -> commercial/industrial prices by utility, county, facility.

Source: https://www.eia.gov/electricity/data/eia861/  (annual zips; 2025 = latest final, released
2026-10-07, at zip/f8612025.zip; 2019-2024 at archive/zip/f861YYYY.zip).

Price definition: revenue (thousand $) / sales (MWh) * 100 -> cents/kWh, from Sales_Ult_Cust
sheet "States", using BUNDLED service rows only (Parts A and D). Delivery-only (Part C) and
energy-only (Part B) rows would give partial prices, so they are kept separately (sales/revenue
columns *_delivery / *_energy) but not in price_com / price_ind. Utility 99999 (state adjustment)
dropped. Short-form (861S) utilities report only totals, so they have no sector prices.

County price: Service_Territory sheet "Counties_States" (utility x state x county NAME) matched to
Census 2020 county FIPS by normalized name. price_*_cty = simple mean across serving utilities with
a bundled price; price_*_cty_w = weighted by each utility's state-level sector sales (a proxy:
county-level sales are not reported).
"""
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, INTER, RAW, UA, log_failure, progress, today, write_source_md

YEARS = range(2019, 2026)
D = RAW / "eia861"
BASE = "https://www.eia.gov/electricity/data/eia861/"


def url_for(y):
    return f"{BASE}zip/f861{y}.zip" if y == max(YEARS) else f"{BASE}archive/zip/f861{y}.zip"


def download():
    D.mkdir(parents=True, exist_ok=True)
    got = []
    for y in YEARS:
        f = D / f"f861{y}.zip"
        if not (f.exists() and f.stat().st_size > 1e6):
            try:
                r = requests.get(url_for(y), headers=UA, timeout=300)
                r.raise_for_status()
                f.write_bytes(r.content)
            except Exception as e:  # noqa
                log_failure("EIA-861", f"f861{y}.zip", str(e)[:150])
                continue
        got.append(y)
    write_source_md(D, f"""
# EIA Form 861 annual electric power industry report (detailed data files)

Page: {BASE}
Files: {', '.join(url_for(y) for y in got)}
Accessed: {today()}
Vintage: data years {min(got)}-{max(got)}; {max(got)} is the final release (EIA page: "October 7, 2026 (final data)").
License: U.S. Government work (EIA), public domain.
Raw zips kept untouched. Sheets used: Sales_Ult_Cust_YYYY.xlsx / States; Service_Territory_YYYY.xlsx / Counties_States.
""")
    return got


def read_sales(z, y):
    name = next(n for n in z.namelist() if re.fullmatch(rf"Sales_Ult_Cust_{y}\.xlsx", n.split("/")[-1]))
    x = pd.read_excel(z.open(name), sheet_name="States", header=2)
    cols = list(x.columns)
    # columns k.. are (rev, sales, cust) x RES, COM, IND, TRANS, TOTAL; k = first 'Thousand Dollars'
    # (2019 has an extra 'Short Form' column before it)
    k = next(i for i, c in enumerate(cols) if str(c).startswith("Thousand"))
    sect = ["res", "com", "ind", "trn", "tot"]
    ren = {cols[0]: "year", cols[1]: "utility_id", cols[2]: "utility_name", cols[3]: "part",
           cols[4]: "service_type", cols[6]: "state", cols[7]: "ownership", cols[8]: "ba_code"}
    for i, s in enumerate(sect):
        ren[cols[k + 3 * i]] = f"rev_{s}"
        ren[cols[k + 1 + 3 * i]] = f"sales_{s}"
        ren[cols[k + 2 + 3 * i]] = f"cust_{s}"
    x = x.rename(columns=ren)
    assert str(cols[k + 1]).startswith("Megawatt") and str(cols[k + 12]).startswith("Thousand")
    x = x[pd.to_numeric(x.year, errors="coerce").notna()].copy()
    x["utility_id"] = pd.to_numeric(x.utility_id, errors="coerce")
    x = x[x.utility_id.notna() & (x.utility_id != 99999)]
    for c in x.columns:
        if c.startswith(("rev_", "sales_", "cust_")):
            x[c] = pd.to_numeric(x[c], errors="coerce")
    x["utility_id"] = x.utility_id.astype(int)
    x["year"] = x.year.astype(int)
    return x


def read_territory(z, y):
    name = next(n for n in z.namelist() if re.fullmatch(rf"Service_Territory_{y}\.xlsx", n.split("/")[-1]))
    t = pd.read_excel(z.open(name), sheet_name="Counties_States")
    t.columns = [str(c).strip() for c in t.columns]
    t = t.rename(columns={"Data Year": "year", "Utility Number": "utility_id", "Utility Name": "utility_name",
                          "Short Form": "short_form", "State": "state", "County": "county"})
    t = t[pd.to_numeric(t.utility_id, errors="coerce").notna()]
    t["utility_id"] = t.utility_id.astype(int)
    t["year"] = y
    return t[["year", "utility_id", "utility_name", "short_form", "state", "county"]]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", "and")
    s = re.sub(r"[.'`]", "", s)
    s = re.sub(r"[-_/,]", " ", s)
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"\bsainte\b", "ste", s)
    s = re.sub(r"\s+(county|parish|borough|census area|city and borough|municipality|municipio)$", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def county_keys():
    g = gpd.read_file(f"zip://{RAW / 'census_geo' / 'cb_2020_us_county_500k.zip'}", ignore_geometry=True)
    g = g[g.STATEFP.astype(int) <= 56]
    rows = []
    for r in g.itertuples():
        base = norm(r.NAME)
        is_city = r.LSAD == "25"  # independent city (VA, MD Baltimore, MO St. Louis, NV Carson City)
        rows.append((r.STUSPS, base + " city" if is_city else base, r.GEOID))
        if is_city:
            # 'Carson City', 'Baltimore City' etc. also appear bare when no county of that name exists
            rows.append((r.STUSPS, base, r.GEOID + "_cityalt"))
    k = pd.DataFrame(rows, columns=["state", "key", "fips"])
    # bare city keys only used where no county with same name exists
    alt = k[k.fips.str.endswith("_cityalt")].copy()
    alt["fips"] = alt.fips.str.replace("_cityalt", "")
    main = k[~k.fips.str.endswith("_cityalt")]
    alt = alt.merge(main[["state", "key"]], how="left", on=["state", "key"], indicator=True)
    alt = alt[alt._merge == "left_only"].drop(columns="_merge")
    k = pd.concat([main, alt], ignore_index=True)
    assert not k.duplicated(["state", "key"]).any()
    return k, g


# manual fixes for names that differ beyond normalization (EIA name -> Census key)
MANUAL = {
    ("AK", "valdez cordova"): None,  # split in 2019 into Chugach / Copper River; cannot assign
    ("IN", "la porte"): "laporte", ("IL", "la salle"): "lasalle", ("IL", "dewitt"): "de witt",
    ("IL", "dupage"): "du page", ("IN", "de kalb"): "dekalb", ("NM", "dona ana"): "dona ana",
    ("LA", "la salle"): "lasalle", ("TX", "de witt"): "dewitt", ("MS", "de soto"): "desoto",
    ("FL", "de soto"): "desoto", ("FL", "miami dade"): "miami dade", ("FL", "dade"): "miami dade",
    ("SD", "shannon"): "oglala lakota", ("AK", "wade hampton"): "kusilvak",
    ("VA", "bedford city"): "bedford",  # Bedford city merged into Bedford County (2013)
    ("AK", "skagway hoonah angoon"): "hoonah angoon", ("AK", "prince of wales outer ketchikan"): "prince of wales hyder",
    ("NM", "debaca"): "de baca", ("MO", "de kalb"): "dekalb", ("AL", "de kalb"): "dekalb",
    ("GA", "de kalb"): "dekalb", ("TN", "de kalb"): "dekalb", ("IL", "de kalb"): "dekalb",
    ("IA", "obrien"): "obrien", ("MD", "baltimore city"): "baltimore city", ("MO", "st louis city"): "st louis city",
}


def match_counties(t, keys):
    t = t.copy()
    t["key"] = t.county.map(norm)
    t["key"] = [MANUAL.get((s, k), k) if (s, k) in MANUAL else k for s, k in zip(t.state, t.key)]
    m = t.merge(keys, how="left", on=["state", "key"])
    # second pass: try dropping/adding ' city', removing spaces
    miss = m.fips.isna() & m.key.notna()
    if miss.any():
        kk = keys.assign(k2=keys.key.str.replace(" ", ""))
        for i in m.index[miss]:
            s, k = m.at[i, "state"], m.at[i, "key"]
            cands = [k.removesuffix(" city"), k + " city", k.replace(" ", "")]
            for c in cands:
                hit = kk[(kk.state == s) & ((kk.key == c) | (kk.k2 == c))]
                if len(hit) == 1:
                    m.at[i, "fips"] = hit.fips.iloc[0]
                    break
    return m


def main():
    years = download()
    sales, terr = [], []
    for y in years:
        with zipfile.ZipFile(D / f"f861{y}.zip") as z:
            sales.append(read_sales(z, y))
            terr.append(read_territory(z, y))
    S = pd.concat(sales, ignore_index=True)
    T = pd.concat(terr, ignore_index=True)
    print("sales rows by year/service:", S.groupby(["year", "service_type"]).size().unstack().to_string())

    # ---- utility x state x year prices
    S["grp"] = S.service_type.str.lower().map({"bundled": "b", "delivery": "delivery", "energy": "energy"})
    agg = {f"{v}_{s}": "sum" for v in ("rev", "sales", "cust") for s in ("res", "com", "ind", "tot")}
    b = S[S.grp == "b"].groupby(["utility_id", "state", "year"]).agg(
        {**agg, "utility_name": "first", "ownership": "first", "ba_code": "first"}).reset_index()
    for s in ("res", "com", "ind", "tot"):
        b[f"price_{s}"] = np.where(b[f"sales_{s}"] > 0, b[f"rev_{s}"] / b[f"sales_{s}"] * 100, np.nan)
    other = S[S.grp != "b"].groupby(["utility_id", "state", "year", "grp"])[["rev_com", "sales_com", "rev_ind", "sales_ind"]].sum().unstack("grp")
    other.columns = [f"{a}_{g}" for a, g in other.columns]
    U = b.merge(other.reset_index(), how="outer", on=["utility_id", "state", "year"])
    U = U.rename(columns={"sales_com": "sales_com_mwh", "sales_ind": "sales_ind_mwh", "sales_res": "sales_res_mwh",
                          "sales_tot": "sales_tot_mwh", "rev_com": "rev_com_k", "rev_ind": "rev_ind_k",
                          "rev_res": "rev_res_k", "rev_tot": "rev_tot_k"})
    names = S.groupby(["utility_id", "state", "year"]).utility_name.first()
    U["utility_name"] = U.set_index(["utility_id", "state", "year"]).index.map(names)
    U["has_bundled"] = U.price_tot.notna() | U.sales_tot_mwh.notna()
    U.to_parquet(CLEAN / "eia861_utility_prices.parquet", index=False)

    # ---- county prices
    keys, g = county_keys()
    T = T[T.state.isin(set(g.STUSPS))]
    M = match_counties(T, keys)
    ucty = M[["state", "county"]].drop_duplicates()
    um = M.drop_duplicates(["state", "county"])
    rate_names = um.fips.notna().mean()
    rate_rows = M.fips.notna().mean()
    unmatched = um[um.fips.isna()][["state", "county"]]
    print(f"county-name match: {rate_names:.4f} of unique (state,county) names ({len(ucty)}); {rate_rows:.4f} of rows")
    print("unmatched:", unmatched.to_string())
    M = M[M.fips.notna()].drop_duplicates(["year", "utility_id", "fips"])
    P = M.merge(U[["utility_id", "state", "year", "price_com", "price_ind", "sales_com_mwh", "sales_ind_mwh"]],
                how="left", on=["utility_id", "state", "year"])

    def summarize(g_):
        out = {}
        for s in ("com", "ind"):
            ok = g_[f"price_{s}"].notna()
            out[f"price_{s}_cty"] = g_.loc[ok, f"price_{s}"].mean() if ok.any() else np.nan
            w = g_.loc[ok, f"sales_{s}_mwh"]
            out[f"price_{s}_cty_w"] = np.average(g_.loc[ok, f"price_{s}"], weights=w) if ok.any() and w.sum() > 0 else np.nan
            out[f"n_util_{s}_price"] = int(ok.sum())
        out["n_utilities"] = g_.utility_id.nunique()
        return pd.Series(out)

    C = P.groupby(["fips", "year"]).apply(summarize, include_groups=False).reset_index()
    C.to_parquet(CLEAN / "county_elec_price.parquet", index=False)

    # ---- facility prices via UTILITY_CODE: latest year with a bundled price for that utility x state
    fac = pd.read_parquet(INTER / "aterio_facility.parquet", columns=["ATERIO_DATA_CENTER_UID", "UTILITY_CODE", "UTILITY_NAME", "STATE_CODE"])
    yl = max(years)
    fac["utility_id"] = pd.to_numeric(fac.UTILITY_CODE, errors="coerce").astype("Int64")
    f2 = fac.copy()
    for s_ in ("ind", "com"):
        best = (U[U[f"price_{s_}"].notna()].sort_values("year").groupby(["utility_id", "state"]).last()
                .reset_index()[["utility_id", "state", "year", f"price_{s_}"]]
                .rename(columns={"state": "STATE_CODE", "year": f"price_{s_}_year", f"price_{s_}": f"price_{s_}_util"}))
        f2 = f2.merge(best, how="left", on=["utility_id", "STATE_CODE"])
    nm = U.sort_values("year").groupby(["utility_id", "state"]).utility_name.last().rename("eia_utility_name").reset_index()
    f2 = f2.merge(nm.rename(columns={"state": "STATE_CODE"}), how="left", on=["utility_id", "STATE_CODE"])
    in_sales_state = f2.eia_utility_name.notna()
    any_861 = set(U.utility_id) | set(T.utility_id)
    f2["match"] = np.select(
        [f2.utility_id.isna(), f2.price_ind_year.eq(yl), f2.price_ind_util.notna(), in_sales_state,
         f2.utility_id.isin(set(U.utility_id)), f2.utility_id.isin(any_861)],
        ["no_utility_code", f"matched_{yl}", "matched_earlier_year", "matched_no_ind_price",
         "id_in_861_sales_other_state", "id_only_in_service_territory"],
        default="id_not_in_861")
    f2 = f2[["ATERIO_DATA_CENTER_UID", "UTILITY_CODE", "STATE_CODE", "eia_utility_name", "price_ind_util", "price_ind_year",
             "price_com_util", "price_com_year", "match"]]
    f2.to_parquet(CLEAN / "facility_elec_price.parquet", index=False)
    if (f2.match == "id_only_in_service_territory").any():
        log_failure("EIA-861", "utility price for TX wires-only utilities (Oncor 44372, CenterPoint 8901, AEP Texas 20404/3278)",
                    "ERCOT delivery-only utilities have no rows in Sales_Ult_Cust 'States' (competitive retail), so no utility price; "
                    f"{int((f2.match == 'id_only_in_service_territory').sum())} facilities unmatched; use county price instead")

    print("\n==== REPORT")
    print("utility-state-year rows:", len(U), "by year:", U.groupby("year").size().to_dict())
    print(U[U.year == yl][["price_com", "price_ind"]].describe().T)
    lv = U[U.year == yl]
    print("US sales-weighted price latest (bundled): com",
          round(lv.rev_com_k.sum() / lv.sales_com_mwh.sum() * 100, 2), "ind", round(lv.rev_ind_k.sum() / lv.sales_ind_mwh.sum() * 100, 2))
    print("county-year rows:", len(C), "counties latest year:", (C.year == yl).sum())
    print(C[C.year == yl].describe().T)
    print("facility match:", f2.match.value_counts().to_dict())
    hc = f2.UTILITY_CODE.notna()
    print(f"of facilities with UTILITY_CODE ({hc.sum()}): utility-state found {f2.eia_utility_name[hc].notna().mean():.3f}; ind price any year {f2.price_ind_util[hc].notna().mean():.3f}; ind price {yl} {(f2.match[hc] == f'matched_{yl}').mean():.3f}")
    print("price_ind_year:", f2.price_ind_year.value_counts().to_dict())
    print("territory-only examples:", f2[f2.match == "id_only_in_service_territory"][["UTILITY_CODE", "STATE_CODE"]].value_counts().head(10).to_dict())
    print("matched_no_ind_price examples:", f2[f2.match == "matched_no_ind_price"].eia_utility_name.value_counts().head(10).to_dict())
    print("other-state examples:", f2[f2.match == "id_in_861_sales_other_state"][["UTILITY_CODE", "STATE_CODE"]].value_counts().head(10).to_dict())
    print(f2.price_ind_util.describe())
    progress(f"31_pull_eia861: years {years}; utility rows {len(U)}; county name match {rate_names:.3f}; "
             f"facility ind-price match (any year) {f2.price_ind_util[hc].notna().mean():.3f} of those with UTILITY_CODE")


if __name__ == "__main__":
    main()
