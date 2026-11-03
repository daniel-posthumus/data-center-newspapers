"""01a — Download CBP county files 2005-2023 (bulk, no API key) + county population.

The Census API (api.census.gov) now returns a 'missing_key' redirect for keyless
requests (checked 2026-11-03), so we use the bulk county files instead:
    https://www2.census.gov/programs-surveys/cbp/datasets/{year}/cbp{yy}co.zip
Raw files are saved untouched under data/raw/cbp/.
"""
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import RAW, UA, log_failure, progress, today, write_source_md

out = RAW / "cbp"
out.mkdir(parents=True, exist_ok=True)
got = []
for y in range(2005, 2024):
    yy = f"{y % 100:02d}"
    url = f"https://www2.census.gov/programs-surveys/cbp/datasets/{y}/cbp{yy}co.zip"
    f = out / f"cbp{yy}co.zip"
    if f.exists() and f.stat().st_size > 1e5:
        got.append((y, url, f.stat().st_size)); continue
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=300)
            r.raise_for_status()
            f.write_bytes(r.content)
            got.append((y, url, len(r.content)))
            break
        except Exception as e:  # noqa
            time.sleep(5)
            if attempt == 2:
                log_failure("CBP", f"county file {y}", repr(e)[:200])

# Census API failure (keyless) is logged for the memo
log_failure("Census API (api.census.gov)", "CBP / ACS via API",
            "keyless requests redirect to missing_key.html (HTTP 302); used bulk files on www2.census.gov instead. Free key would help.")

write_source_md(out, f"""
# County Business Patterns (CBP), county files

- URL pattern: https://www2.census.gov/programs-surveys/cbp/datasets/{{year}}/cbp{{yy}}co.zip
- Years: {', '.join(str(g[0]) for g in got)}
- Access date: {today()}
- Vintage: annual CBP, latest available = 2023 (2024 not posted as of access date).
- NAICS vintages: 2002 (2005-07), 2007 (2008-11), 2012 (2012-16), 2017 (2017-21), 2022 (2022-23).
  Newspaper publishers = 511110 through NAICS 2017; 513110 in NAICS 2022. Verified from file contents by 01b.
- License: U.S. Government work, public domain.
- Files untouched as downloaded. Sizes (bytes): {', '.join(f'{g[0]}:{g[2]}' for g in got)}
""")
progress(f"01a CBP downloads: {len(got)} of 19 years")
