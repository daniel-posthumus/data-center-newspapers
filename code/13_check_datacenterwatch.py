"""Check whether Data Center Watch (datacenterwatch.org) publishes a DOWNLOADABLE project-level list.

Only normal GETs of public pages listed in the site's sitemap.xml (no interactive map, no /api/,
no ?format=json — all disallowed or out of scope). 2s between requests.
Looks for links to .csv/.xlsx/.xls/.pdf/Google Sheets/Airtable/Drive downloads on each page.
Raw HTML of the inspected pages is saved untouched to data/raw/datacenterwatch/<date>/pages/.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import pypdf
import requests
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, INTER, OUTLOGS, RAW, UA, log_failure, progress, save_table, today, write_source_md  # noqa: E402

REPORT_PDF = "https://www.datacenterwatch.org/s/Data-Center-Watch-Report.pdf"
STATES = {"Arizona": "AZ", "Missouri": "MO", "Indiana": "IN", "Virginia": "VA", "Oregon": "OR",
          "Texas": "TX", "California": "CA"}
ITEM_RE = re.compile(
    r"^\s*(\d+)\.\s+(.+?),\s+(Arizona|Missouri|Indiana|Virginia|Oregon|Texas|California)\.\s+"
    r"(\$\s?[\d.]+\s(?:billion|million)|Investment undisclosed)[.,]\s+(.+?)\s+—\s*(Blocked|Delayed)(.*)$"
)


def parse_report(pdf: Path) -> pd.DataFrame:
    """Parse the enumerated blocked/delayed project list (pp. 8+) of the free 2023-Q1 2025 report."""
    r = pypdf.PdfReader(pdf)
    text = "\n".join(pg.extract_text() for pg in r.pages[7:])
    rows = []
    for ln in text.splitlines():
        m = ITEM_RE.match(ln)
        if m:
            n, place, state, inv, who, status, rest = m.groups()
            who = who.strip().rstrip(".").replace("  ", " ")
            rows.append(dict(dcw_n=int(n), place=place.strip(), state=STATES[state], investment=inv.replace("$ ", "$"),
                             name_developer=who, dcw_status=status, status_note=rest.strip(" ()")))
    df = pd.DataFrame(rows)
    def usd(x):
        m = re.match(r"\$([\d.]+)\s(billion|million)", x)
        return float(m.group(1)) * (1e9 if m.group(2) == "billion" else 1e6) if m else None
    df["investment_usd"] = df["investment"].map(usd)
    df["source"] = "DCW report '$64 billion ... blocked or delayed' (research timeline May 2024-Mar 2025)"
    return df


def norm(x) -> str:
    x = str(x or "").lower()
    x = re.sub(r"\b(county|city|town|of|data centers?|llc|inc)\b", " ", x)
    return re.sub(r"[^a-z0-9 ]", " ", x).strip()


def match_aterio(dcw: pd.DataFrame) -> pd.DataFrame:
    a = pd.read_parquet(INTER / "aterio_facility.parquet")
    a = a[a["is_us"]] if "is_us" in a else a
    a["campus"] = a["ATERIO_DATA_CENTER_CAMPUS_UID"].fillna(a["ATERIO_DATA_CENTER_UID"])
    camp = a.groupby("campus").agg(
        state=("STATE_CODE", "first"), city=("CITY_NAME", "first"), county=("COUNTY_NAME", "first"),
        campus_name=("DATA_CENTER_CAMPUS_NAME", "first"), provider=("PROVIDER_NAME", "first"),
        stages=("DATA_CENTER_STAGE", lambda s: "; ".join(sorted(set(s.dropna())))),
        n_fac=("ATERIO_DATA_CENTER_UID", "size"),
    ).reset_index()
    out = []
    for _, d in dcw.iterrows():
        c = camp[camp["state"].eq(d["state"])].copy()
        pl = norm(d["place"])
        c["place_score"] = c.apply(lambda r: max(fuzz.token_set_ratio(pl, norm(r["city"])),
                                                 fuzz.token_set_ratio(pl, norm(r["county"])),
                                                 fuzz.partial_ratio(pl, norm(r["campus_name"])) if r["campus_name"] else 0), axis=1)
        dv = norm(d["name_developer"])
        c["dev_score"] = c.apply(lambda r: max(fuzz.token_set_ratio(dv, norm(r["provider"])),
                                               fuzz.token_set_ratio(dv, norm(r["campus_name"]))), axis=1)
        c["score"] = 0.5 * c["place_score"] + 0.5 * c["dev_score"]
        c = c.sort_values("score", ascending=False)
        best = c.head(1)
        rec = d.to_dict()
        n_place = int((c["place_score"] >= 90).sum())
        rec["n_aterio_campuses_same_place"] = n_place
        if len(best):
            b = best.iloc[0]
            rec.update(aterio_campus=b["campus"], aterio_campus_name=b["campus_name"], aterio_provider=b["provider"],
                       aterio_city=b["city"], aterio_county=b["county"], aterio_stages=b["stages"],
                       place_score=b["place_score"], dev_score=b["dev_score"])
            # rule: place must match well; developer either matches or campus name matches
            rec["matched"] = bool(b["place_score"] >= 90 and b["dev_score"] >= 80)
        else:
            rec["matched"] = False
        out.append(rec)
    return pd.DataFrame(out)

SITE = "https://www.datacenterwatch.org"
DL_RE = re.compile(
    r"""(?:href|src|data-url)=["']([^"']+?(?:\.csv|\.xlsx?|\.pdf|docs\.google\.com/spreadsheets[^"']*|airtable\.com[^"']*|drive\.google\.com[^"']*|dropbox\.com[^"']*)(?:\?[^"']*)?)["']""",
    re.I,
)


def main():
    out_dir = RAW / "datacenterwatch" / today()
    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"Data Center Watch download check {today()}"]
    robots = requests.get(SITE + "/robots.txt", headers=UA, timeout=30).text
    (out_dir / "robots.txt").write_text(robots)
    lines.append("robots.txt: Squarespace default; disallows /api/, /search, ?format=json etc.; no blanket Disallow for * (AI-bot group shares the same rules).")
    sm = requests.get(SITE + "/sitemap.xml", headers=UA, timeout=30).text
    (out_dir / "sitemap.xml").write_text(sm)
    urls = re.findall(r"<loc>([^<]+)</loc>", sm)
    # skip boilerplate newsletter template pages? keep all; site is small
    found = {}
    for u in urls:
        time.sleep(2)
        try:
            r = requests.get(u, headers=UA, timeout=60)
        except Exception as e:  # noqa: BLE001
            lines.append(f"  {u}: error {e}")
            continue
        name = re.sub(r"[^A-Za-z0-9]+", "_", u.replace(SITE, "")).strip("_") or "home"
        (pages_dir / f"{name}.html").write_text(r.text)
        links = sorted({urljoin(u, m) for m in DL_RE.findall(r.text)})
        title = re.search(r"<title>(.*?)</title>", r.text, re.S)
        price = re.findall(r'"price(?:Money)?"\s*:\s*\{[^}]*"value"\s*:\s*"?([\d.]+)', r.text)
        lines.append(f"  {u} [{r.status_code}] title={title.group(1).strip()[:80] if title else ''!r} downloads={len(links)}" + (f" price={price[:1]}" if price else ""))
        for link in links:
            lines.append(f"      -> {link}")
            found.setdefault(link, u)
    write_source_md(
        out_dir,
        f"""
# Data Center Watch (datacenterwatch.org) — site check
- Pages from {SITE}/sitemap.xml fetched {today()} (normal GET, 2s delay); raw HTML in pages/.
- Interactive map and its API NOT accessed (per instructions; /api/ is robots-disallowed).
- Purpose: determine whether a downloadable project-level list exists.
- Data-Center-Watch-Report.pdf: free report "$64 billion of data center projects have been blocked or delayed
  amid local opposition" ({REPORT_PDF}), research timeline May 2024 - March 2025; contains a 16-project list.
- License: DCW copyright; local research use only, no redistribution.
""",
    )
    data_links = [k for k in found if re.search(r"\.(csv|xlsx?)\b|spreadsheets|airtable", k, re.I)]
    pdf_links = [k for k in found if re.search(r"\.pdf\b", k, re.I)]
    lines.append(f"candidate data-file links (csv/xlsx/sheets/airtable): {data_links}")
    lines.append(f"pdf links: {pdf_links}")
    # --- the free report PDF contains an enumerated project list -> parse + match
    pdf = out_dir / "Data-Center-Watch-Report.pdf"
    if not pdf.exists():
        time.sleep(2)
        pdf.write_bytes(requests.get(REPORT_PDF, headers=UA, timeout=120).content)
    dcw = parse_report(pdf)
    dcw.to_parquet(CLEAN / "dcw_projects.parquet", index=False)
    lines.append(f"Parsed {len(dcw)} projects from {REPORT_PDF}: {dcw['dcw_status'].value_counts().to_dict()}")
    m = match_aterio(dcw)
    save_table(m.drop(columns=["source"]), "dcw_aterio_match")
    lines.append(f"matched to an Aterio campus (place>=90 & developer/name>=80): {m['matched'].sum()} of {len(m)}")
    neg = r"Not Approved/Withdrawn|Cancelled|Delayed"
    mm = m[m["matched"]]
    lines.append(f"  of matched, Aterio stage includes Not Approved/Withdrawn/Cancelled/Delayed: {mm['aterio_stages'].str.contains(neg).sum()}")
    lines.append(m[["dcw_n", "place", "state", "name_developer", "dcw_status", "matched", "aterio_campus_name", "aterio_provider", "aterio_city", "aterio_stages", "place_score", "dev_score"]].to_string())
    lines.append("Later quarterly reports (Q2 2025 ... Q2 2026) are HTML summaries only; project-level reports are sold in /shop ($250 'Insights', $2,500 'In-depth').")
    log_failure("Data Center Watch", "project-level list after Q1 2025", "no free download; only the 2023-Q1 2025 report PDF has a 16-project list; later reports are paid ($250/$2,500); map/API not used")
    (OUTLOGS / "13_check_datacenterwatch.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    progress(f"13_check_datacenterwatch: {len(urls)} pages checked; data links={len(data_links)} pdf={len(pdf_links)}")


if __name__ == "__main__":
    main()
