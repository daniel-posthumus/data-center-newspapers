"""33 — County broadband availability.

Preferred source: FCC National Broadband Map (BDC) "Summary by Geography" downloads.
Checked 2026-11-03: broadbandmap.fcc.gov returns HTTP 403 "Access Denied" (Akamai) to scripted
requests, and the documented public BDC API requires a registered username + API token. Not
"easily downloadable without login" -> logged as a failure, not used.

Fallback actually used: FCC Form 477 "Area Table June 2021 Status V1" (the last Form 477 vintage)
from FCC Open Data (Socrata dataset xvwq-qtaj), public domain. County rows; population-based
(FCC block population estimates), not location-based. Speed tiers are download/upload pairs
0.2/0.2, 4/1, 10/1, 25/3, 100/10, 250/25, 1000/100 -> there is NO 100/20 tier; we report 100/10.

Output: data/clean/county_broadband.parquet
  fips, share_pop_100_10_terr (>=1 terrestrial fixed provider [ADSL/cable/fiber/other/fixed wireless,
  excl. satellite] at >=100/10), share_pop_25_3_terr, share_pop_fiber (>=1 fiber provider, any speed),
  pop_477, vintage
"""
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, RAW, UA, log_failure, progress, today, write_source_md

D = RAW / "fcc_broadband"
NBM = "https://broadbandmap.fcc.gov/data-download/nationwide-data"
DS = "xvwq-qtaj"
URL = f"https://opendata.fcc.gov/resource/{DS}.csv"
VINTAGE = "FCC Form 477 area table, June 2021 (status V1)"


def try_nbm():
    try:
        r = requests.get(NBM, headers=UA, timeout=60)
        return r.status_code
    except Exception as e:  # noqa
        return str(e)[:100]


def main():
    D.mkdir(parents=True, exist_ok=True)
    st = try_nbm()
    print("NBM page status:", st)
    if st != 200:
        log_failure("FCC National Broadband Map", "county Summary by Geography (BDC)",
                    f"broadbandmap.fcc.gov returned {st} (Access Denied) to scripted requests; public BDC API needs "
                    "registered username+token. Fell back to Form 477 June 2021 area table (opendata.fcc.gov xvwq-qtaj)")
    f = D / "form477_area_table_jun2021_county.csv"
    params = {"$where": "type='county' AND ((tech='acfow' AND speed in('25','100')) OR (tech='f' AND speed='0.2'))",
              "$limit": 500000, "$order": "id,tech,speed,urban_rural,tribal_non"}
    if not (f.exists() and f.stat().st_size > 1e5):
        r = requests.get(URL, params=params, headers=UA, timeout=600)
        r.raise_for_status()
        f.write_bytes(r.content)
    write_source_md(D, f"""
# FCC fixed broadband availability (county)

Preferred: FCC National Broadband Map ({NBM}) — NOT used: HTTP {st} to scripted access on {today()};
BDC public API requires registered username + token.

Used: FCC Open Data, "Area Table June 2021 Status V1" (Form 477), dataset id {DS}
URL: {URL}
Query: {params}
Accessed: {today()}
Vintage: Form 477 data as of June 30, 2021 (last Form 477 round). Urban/rural split per 2010 SF-1; population counts are FCC block-level estimates (county sum = 329.5M, i.e. not 2010 census counts).
License: Public Domain U.S. Government.
tech: a=ADSL c=cable f=fiber o=other copper s=satellite w=fixed wireless (combination = any of).
speed: 0.2/0.2, 4/1, 10/1, 25/3, 100/10, 250/25, 1000/100 (download Mbps listed).
""")
    x = pd.read_csv(f, dtype={"id": str, "speed": str})
    for c in ("has_0", "has_1", "has_2", "has_3more"):
        x[c] = pd.to_numeric(x[c])
    x["pop"] = x[["has_0", "has_1", "has_2", "has_3more"]].sum(axis=1)
    x["pop_any"] = x["pop"] - x.has_0
    g = x.groupby(["id", "tech", "speed"])[["pop", "pop_any"]].sum().reset_index()
    g["share"] = g.pop_any / g["pop"]
    w = g.pivot_table(index="id", columns=["tech", "speed"], values="share")
    pop = g[(g.tech == "acfow") & (g.speed == "100")].set_index("id")["pop"]
    out = pd.DataFrame({
        "fips": w.index.str.zfill(5),
        "share_pop_100_10_terr": w[("acfow", "100")].values,
        "share_pop_25_3_terr": w[("acfow", "25")].values,
        "share_pop_fiber": w[("f", "0.2")].values,
        "pop_477": pop.reindex(w.index).values,
    })
    out = out[out.fips.str[:2].astype(int) <= 56]
    out["vintage"] = VINTAGE
    out.to_parquet(CLEAN / "county_broadband.parquet", index=False)
    print("\n==== REPORT")
    print("counties:", len(out))
    print(out.describe().T)
    tot = out.pop_477.sum()
    print("pop-weighted national: 100/10 terr", (out.share_pop_100_10_terr * out.pop_477).sum() / tot,
          "fiber", (out.share_pop_fiber * out.pop_477).sum() / tot, "pop", tot)
    progress(f"33_pull_broadband: NBM blocked ({st}); used {VINTAGE}; {len(out)} counties")


if __name__ == "__main__":
    main()
