"""02a — Download QCEW county data for newspaper publishers (and NAICS 493 warehousing).

Why QCEW matters more than the brief anticipated: from the 2017 vintage onward, CBP
county files drop every 6-digit NAICS cell with fewer than 3 establishments (see 01b),
so CBP cannot distinguish 0/1/2 newspaper establishments after 2016. QCEW publishes
establishment counts for every county-industry cell (only employment/wages are suppressed).

Sources:
  2014-2025: BLS QCEW open-data CSV slices (annual averages, all areas for one industry)
      https://data.bls.gov/cew/data/api/{year}/a/industry/{naics}.csv
      newspaper NAICS: 511110 through 2021, 513110 from 2022 (NAICS 2022)  [verified by HTTP probe]
  2005-2013: BLS bulk annual "by industry" zips (the API slices start in 2014)
      https://data.bls.gov/cew/data/files/{year}/csv/{year}_annual_by_industry.zip
Raw files saved untouched under data/raw/qcew/.
"""
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import RAW, UA, log_failure, progress, today, write_source_md

out = RAW / "qcew"
out.mkdir(parents=True, exist_ok=True)
log = []


def fetch(url, f, timeout=900):
    if f.exists() and f.stat().st_size > 1000:
        return True
    for attempt in range(3):
        try:
            with requests.get(url, headers=UA, timeout=timeout, stream=True) as r:
                if r.status_code == 404:
                    return False
                r.raise_for_status()
                tmp = f.with_suffix(f.suffix + ".part")
                with tmp.open("wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
                tmp.rename(f)
            return True
        except Exception as e:  # noqa
            time.sleep(10)
            if attempt == 2:
                log_failure("QCEW", url, repr(e)[:200])
    return False


for y in range(2014, 2026):
    for naics in (["511110"] if y <= 2021 else ["513110"]) + ["493"]:
        url = f"https://data.bls.gov/cew/data/api/{y}/a/industry/{naics}.csv"
        ok = fetch(url, out / f"api_{y}_a_{naics}.csv")
        log.append(f"{y} {naics} api: {'ok' if ok else 'MISSING'}")

for y in range(2005, 2014):
    url = f"https://data.bls.gov/cew/data/files/{y}/csv/{y}_annual_by_industry.zip"
    ok = fetch(url, out / f"{y}_annual_by_industry.zip")
    log.append(f"{y} bulk by_industry: {'ok' if ok else 'MISSING'}")

print("\n".join(log))
write_source_md(out, f"""
# BLS Quarterly Census of Employment and Wages (QCEW), annual averages

- 2014-2025: https://data.bls.gov/cew/data/api/{{year}}/a/industry/{{naics}}.csv  (open-data slices)
- 2005-2013: https://data.bls.gov/cew/data/files/{{year}}/csv/{{year}}_annual_by_industry.zip  (bulk)
- Industries: newspaper publishers 511110 (NAICS 2017 and earlier, used through 2021),
  513110 (NAICS 2022, used 2022+); warehousing & storage 493 (placebo).
- Access date: {today()}
- Coverage: UI-covered establishments. Establishment counts are published for every cell;
  employment and wages are suppressed (disclosure_code = 'N') when confidential.
- License: U.S. Government work, public domain.
- Download log:
{chr(10).join('  - ' + l for l in log)}
""")
progress("02a QCEW downloads finished: " + "; ".join(l for l in log if "MISSING" in l) or "all ok")
