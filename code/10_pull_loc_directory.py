"""Pull the Library of Congress "Directory of U.S. Newspapers in American Libraries"
(the former Chronicling America title directory, now served from loc.gov) via the
loc.gov JSON API, and build a title-level table with place and start/end years.

Source: https://www.loc.gov/collections/directory-of-us-newspapers-in-american-libraries/?fo=json
The legacy chroniclingamerica.loc.gov/search/titles/results JSON endpoint now 308-redirects
to www.loc.gov/chroniclingamerica/... which sits behind a Cloudflare JS challenge, so it is
not used. loc.gov robots.txt sets Crawl-Delay: 5 -> we sleep 5s between requests.

Raw pages are cached (gzipped JSON, untouched) under data/raw/loc_directory/<date>/pages/,
so re-runs resume. Output: data/clean/loc_newspapers.parquet.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, OUTLOGS, RAW, UA, log_failure, progress, today, write_source_md  # noqa: E402

BASE = "https://www.loc.gov/collections/directory-of-us-newspapers-in-american-libraries/"
PER = 500
DELAY = 5.0  # robots.txt Crawl-Delay
SRC = RAW / "loc_directory"
# reuse the most recent pull directory if one exists (resume), else start today's
_existing = sorted(p for p in SRC.glob("20*") if p.is_dir()) if SRC.exists() else []
PULL = _existing[-1] if _existing else SRC / today()
PAGES = PULL / "pages"
PAGES.mkdir(parents=True, exist_ok=True)


# A full pull (~159k items, 160 pages of 1000) proved too slow: ~100 s/page with frequent
# IncompleteRead errors -> ~4 h. We therefore pull three subsets (raw pages cached per subset):
#   national_2000_2026 : dates=2000/2026 (loc.gov date facet; overlap filter -- verified it returns
#                        open-ended '[1900 TO 9999]' titles and closed '[1937 TO 2009]' titles).
#                        CAVEAT: records with no 'dates' field are not returned by this filter.
#   state_texas, state_virginia : full state subsets (no date filter) for complete TX/VA coverage.
SUBSETS = {
    "national_2000_2026": "dates=2000/2026",
    "state_texas": "fa=location_state:texas",
    "state_virginia": "fa=location_state:virginia",
}


def get_page(subset: str, query: str, sp: int) -> dict | None:
    d = PAGES / subset
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"page_{sp:04d}.json.gz"
    if f.exists():
        return json.loads(gzip.decompress(f.read_bytes()))
    url = f"{BASE}?fo=json&c={PER}&sp={sp}&{query}&at=results,pagination"
    for attempt in range(6):
        try:
            r = requests.get(url, headers=UA, timeout=300)
            if r.status_code == 200:
                js = r.json()
                f.write_bytes(gzip.compress(r.content))
                time.sleep(DELAY)
                return js
            print(f"{subset} page {sp}: HTTP {r.status_code}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"{subset} page {sp}: {str(e)[:120]}", flush=True)
        time.sleep(DELAY * (attempt + 2))
    return None


def fetch_all():
    results, totals, missing = [], {}, []
    for subset, query in SUBSETS.items():
        first = get_page(subset, query, 1)
        if first is None:
            log_failure("LoC newspaper directory", f"{subset} page 1", "request failed")
            continue
        n = first["pagination"]["of"]
        totals[subset] = n
        n_pages = -(-n // PER)
        print(f"{subset}: {n} items, {n_pages} pages", flush=True)
        res = [dict(r, _subset=subset) for r in first["results"]]
        for sp in range(2, n_pages + 1):
            d = get_page(subset, query, sp)
            if d is None:
                missing.append((subset, sp))
                continue
            res.extend(dict(r, _subset=subset) for r in d["results"])
            print(f"{subset} page {sp}/{n_pages}", flush=True)
        results.extend(res)
    if missing:
        log_failure("LoC newspaper directory", f"pages {missing}", "request failed after retries")
    # collection total (for reporting)
    tot = requests.get(f"{BASE}?fo=json&c=1&at=pagination", headers=UA, timeout=120).json()["pagination"]["of"]
    totals["collection_total"] = tot
    return results, totals, missing


YR_RE = re.compile(r"\s(\d[\d?]{3}|\?{4})-(\d[\d?]{3}|\?{4}|Current|current)(?=\s|$)")


def first(x):
    if isinstance(x, list):
        return x[0] if x else None
    return x


def parse(results: list[dict]) -> pd.DataFrame:
    rows = []
    for r in results:
        it = r.get("item", {}) or {}
        title = r.get("title") or ""
        m = YR_RE.search(title)
        start_raw, end_raw = (m.group(1), m.group(2)) if m else (None, None)
        dates = first(r.get("dates")) or ""
        dm = re.match(r"\[(\d{4}) TO (\d{4})\]", dates)
        d0, d1 = (int(dm.group(1)), int(dm.group(2))) if dm else (None, None)
        rows.append(
            dict(
                lccn=first(r.get("number_lccn")),
                title=title,
                type=first(r.get("type")),
                country=first(r.get("location_country")),
                state=first(r.get("location_state")),
                county=first(r.get("location_county")),
                city=first(r.get("location_city")),
                n_places=len([c for c in r.get("composite_location", []) if c.startswith("3/")]),
                start_year_raw=start_raw,
                end_year_raw=end_raw,
                dates_start=d0,
                dates_end=d1,
                created_published=first(it.get("created_published")),
                frequency=first(r.get("publication_frequency")),
                digitized=r.get("digitized"),
                url=r.get("url"),
                subset=r.get("_subset", "spot"),
            )
        )
    df = pd.DataFrame(rows)

    def yr(s):
        return int(s) if isinstance(s, str) and s.isdigit() else None

    df["start_year"] = df["start_year_raw"].map(yr).astype("Int64")
    df["end_year"] = df["end_year_raw"].map(yr).astype("Int64")
    er = df["end_year_raw"].fillna("")
    df["end_open"] = er.str.lower().eq("current") | er.eq("????")
    df["end_uncertain"] = er.str.contains(r"\?") & ~er.eq("????")  # e.g. 19??, 200?
    # loc 'dates' field replaces ? by 9 (upper bound); keep as bound
    df["end_year_bound"] = df["dates_end"].astype("Int64")
    df["start_year_bound"] = df["dates_start"].astype("Int64")
    df["subsets"] = df.groupby("lccn")["subset"].transform(lambda x: ",".join(sorted(set(x))))
    df = df.drop_duplicates("lccn").drop(columns="subset")
    return df


def stats(label: str, us: pd.DataFrame) -> list[str]:
    L = [f"=== {label}: {len(us)} titles"]
    # active in/after 2000: start <= 2025 and (end bound >= 2000 or open end)
    endb = us["end_year_bound"]
    act = us[(us["start_year_bound"].fillna(0) <= 2025) & ((endb >= 2000) | us["end_open"])]
    variant = act["title"].str.contains(r"\[(?:Online Resource|Microfilm Reel)\]", regex=True)
    L.append(f"active in/after 2000 (end bound>=2000 or open): {len(act)} (of which format-variant records "
             f"'[Online Resource]'/'[Microfilm Reel]': {variant.sum()})")
    for nm, a in (("all records", act), ("excl. format variants", act[~variant])):
        real_end = a["end_year"].notna() & ~a["end_open"]
        L.append(f"  [{nm}] n={len(a)}; exact numeric end year: {real_end.sum()} ({real_end.mean():.3f}); "
                 f"open end (Current/????): {a['end_open'].sum()} ({a['end_open'].mean():.3f}); "
                 f"uncertain end (e.g. 200?): {a['end_uncertain'].sum()}; of open: 'Current'="
                 f"{a['end_year_raw'].fillna('').str.lower().eq('current').sum()}, '????'={a['end_year_raw'].eq('????').sum()}")
    a = act[~variant]
    real_end = a["end_year"].notna() & ~a["end_open"]
    dist = a.loc[real_end, "end_year"].value_counts().sort_index()
    dist = dist[(dist.index >= 2000) & (dist.index <= 2026)]
    L.append("  exact end-year distribution 2000-2026 (excl. variants): " + ", ".join(f"{int(k)}:{v}" for k, v in dist.items()))
    sd = a["start_year"].value_counts().sort_index()
    L.append("  start-year counts 2000-2026 (excl. variants): " + ", ".join(f"{int(k)}:{v}" for k, v in sd[sd.index >= 2000].items()))
    return L


# Known closures (and controls) to spot-check. 'expect' is from general knowledge, for comparison only.
SPOT = [
    ("vindicator", "ohio", "Vindicator (Youngstown) - closed Aug 2019"),
    ("tampa bay times", "florida", "Tampa Bay Times - open (control)"),
    ("rocky mountain news", "colorado", "Rocky Mountain News (Denver) - closed Feb 2009"),
    ("seattle post-intelligencer", "washington", "Seattle P-I - print ended Mar 2009 (online continues)"),
    ("daily iowan", "iowa", "Daily Iowan (Iowa City) - open (control)"),
    ("tribune-review", "pennsylvania", "Pittsburgh Tribune-Review - print ended Nov 2016 (online continues)"),
    ("village voice", "new york", "Village Voice - print ended 2017 (later revived)"),
    ("city paper", "maryland", "Baltimore City Paper - closed Nov 2017"),
    ("houston press", "texas", "Houston Press - print ended Nov 2017"),
    ("tucson citizen", "arizona", "Tucson Citizen - print closed May 2009"),
    ("albuquerque tribune", "new mexico", "Albuquerque Tribune - closed Feb 2008"),
    ("ann arbor news", "michigan", "Ann Arbor News - closed Jul 2009"),
]


def spot_checks() -> list[str]:
    """Targeted title searches (q=...&fa=location_state:...) for known closures; raw saved."""
    L = ["=== Spot checks (targeted API searches; titles whose end year >= 1990 or open shown)"]
    d = PAGES / "spot_checks"
    d.mkdir(parents=True, exist_ok=True)
    for q, st, note in SPOT:
        f = d / f"{re.sub('[^a-z]+', '_', q)}_{st.replace(' ', '_')}.json.gz"
        if not f.exists():
            r = requests.get(BASE, params={"fo": "json", "c": 100, "q": q, "fa": f"location_state:{st}", "at": "results"},
                             headers=UA, timeout=120)
            f.write_bytes(gzip.compress(r.content))
            time.sleep(DELAY)
        res = json.loads(gzip.decompress(f.read_bytes())).get("results", [])
        sub = parse(res) if res else pd.DataFrame()
        L.append(f"- {note}")
        if sub.empty:
            L.append("    (no results)")
            continue
        sub = sub[sub["title"].str.lower().str.contains(q.split()[0])]
        keep = sub[(sub["end_year_bound"].fillna(9999) >= 1990) | sub["end_open"]]
        for _, r in keep.iterrows():
            L.append(f"    {r['lccn']}: {r['title']} | end_raw={r['end_year_raw']} | dates_field={r['dates_start']}-{r['dates_end']}")
        if keep.empty:
            L.append(f"    no title with end>=1990/open among {len(sub)} matching titles")
    return L


def main():
    results, total, missing = fetch_all()
    write_source_md(
        PULL,
        f"""
# Library of Congress — Directory of U.S. Newspapers in American Libraries

- URL: {BASE}?fo=json&c={PER}&sp=<page>&<subset query>&at=results,pagination
- Subsets pulled: {SUBSETS} (full pull abandoned as too slow; partial full-pull pages kept in pages_full_partial_abandoned/)
- Access date: {PULL.name} (pages cached; parse run {today()})
- Vintage: loc.gov index; records carry extract_timestamp ~2026-05 and holdings files dated 2025-09-02
- Items reported by API: {total}; pages missing: {missing}
- Raw files: pages/<subset>/page_NNNN.json.gz = untouched API responses (gzip).
- License: Library of Congress catalog/metadata; LoC states no known copyright restrictions on its
  bibliographic metadata (public domain US government work). robots.txt Crawl-Delay 5s respected.
- Notes: legacy chroniclingamerica.loc.gov title-search JSON redirects to a Cloudflare JS challenge; not used.
""",
    )
    df = parse(results)
    out = df.copy()
    out.to_parquet(CLEAN / "loc_newspapers.parquet", index=False)

    lines = [f"LoC directory pull {today()} (SUBSETS, not full directory)", f"API item counts: {total}; parsed unique LCCN: {len(df)}"]
    lines.append(f"type counts: {df['type'].value_counts().to_dict()}")
    lines.append(f"titles with no parsable start year: {df['start_year'].isna().sum()}; no 'dates' field: {df['dates_end'].isna().sum()}")
    us = df[df["country"].eq("united states")]
    lines.append(f"US-located titles in pull: {len(us)}")
    for label, sub in [("ALL pulled US titles", us), ("TX (full state subset)", us[us["state"].eq("texas")]),
                       ("VA (full state subset)", us[us["state"].eq("virginia")])]:
        lines += stats(label, sub)
    lines += spot_checks()
    (OUTLOGS / "10_pull_loc_directory.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    progress(f"10_pull_loc_directory: {len(df)} titles -> data/clean/loc_newspapers.parquet")


if __name__ == "__main__":
    main()
