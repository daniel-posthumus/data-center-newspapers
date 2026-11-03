"""22 — County presidential returns 2000-2024 -> Republican share of total votes.

Preferred source: MEDSL County Presidential Returns 2000-2024, Harvard Dataverse doi:10.7910/DVN/VOQCHQ.
As of 2026-11-03 the Dataverse file download API refuses it ("You may not download this file
without the required Guestbook response for guestbookID 458"), i.e. a guestbook form (identity
info) must be filled in a browser. We do not submit that on the user's behalf. If someone
downloads it manually and saves it as data/raw/medsl/countypres_2000-2024.csv, this script uses it.

Fallback actually used (no forms, no keys):
  * 2000-2016: MEDSL's own GitHub release, https://github.com/MEDSL/county-returns
    (countypres_2000-2016.csv, official state data). Denominator = sum of candidate votes in the
    county (the file's `totalvotes` is inflated ~21% in Virginia, so it is not used).
  * 2020, 2024: tonmcg/US_County_Level_Election_Results_08-24 (MIT licence; compiled by the
    repo author from Fox News / Politico / NYT results pages -- NOT authoritative).
    total_votes = all candidates. 2024 is validated state-by-state against MEDSL's official
    2024-president-state.csv; 2016 tonmcg vs MEDSL is compared at county level as a quality check.
  * Connecticut 2024: tonmcg uses the 9 planning regions; we instead aggregate MEDSL's official
    2024 precinct file for CT (github.com/MEDSL/2024-elections-official, ct24.zip), which carries
    the 8 legacy county FIPS. CT reports both TOTAL and by-mode rows -> TOTAL rows only.
  * Alaska: no source reports by borough (MEDSL 2000-16 and tonmcg use 40 state-house districts,
    whose pseudo-FIPS collide with real borough codes). All AK rows are collapsed to ONE statewide
    row per year with fips '02000' and geo_level='state'.

Output: data/clean/pres_county.parquet
    fips, year, rep_votes, total_votes, rep_share, rep_share_2p, source, geo_level
"""
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import CLEAN, RAW, UA, log_failure, progress, today, write_source_md

out = RAW / "medsl"
out.mkdir(parents=True, exist_ok=True)
TM = "https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/master"
URLS = {
    "countypres_2000-2016.csv": "https://raw.githubusercontent.com/MEDSL/county-returns/master/countypres_2000-2016.csv",
    "County Presidential Returns 2000-2016.md": "https://raw.githubusercontent.com/MEDSL/county-returns/master/County%20Presidential%20Returns%202000-2016.md",
    "2024-president-state.csv": "https://raw.githubusercontent.com/MEDSL/2024-elections-official/main/2024-president-state.csv",
    "precinct_2024/ct24.zip": "https://raw.githubusercontent.com/MEDSL/2024-elections-official/main/individual_states/ct24.zip",
    "tonmcg/2016_US_County_Level_Presidential_Results.csv": f"{TM}/2016_US_County_Level_Presidential_Results.csv",
    "tonmcg/2020_US_County_Level_Presidential_Results.csv": f"{TM}/2020_US_County_Level_Presidential_Results.csv",
    "tonmcg/2024_US_County_Level_Presidential_Results.csv": f"{TM}/2024_US_County_Level_Presidential_Results.csv",
    "tonmcg/LICENSE": f"{TM}/LICENSE",
    "tonmcg/README.md": f"{TM}/README.md",
}
for name, url in URLS.items():
    f = out / name
    f.parent.mkdir(parents=True, exist_ok=True)
    if f.exists() and f.stat().st_size > 0:
        continue
    r = requests.get(url, headers=UA, timeout=300)
    r.raise_for_status()
    f.write_bytes(r.content)

# Record the Dataverse failure (checked live each run)
r = requests.get("https://dataverse.harvard.edu/api/access/datafile/13573089?format=original", headers=UA, timeout=60)
if r.status_code != 200 or "Guestbook" in r.text[:300]:
    log_failure("MEDSL county pres 2000-2024 (Dataverse doi:10.7910/DVN/VOQCHQ)", "file 13573089 via access API",
                "requires Guestbook response (guestbookID 458) - not submitted on user's behalf; used MEDSL GitHub 2000-16 + tonmcg 2020/2024 (+MEDSL CT precincts 2024). Manual download -> data/raw/medsl/countypres_2000-2024.csv")
log_failure("MEDSL 2024 precinct returns (GitHub)", "aggregate all states' precincts to county for 2024",
            "state totals did not reconcile in ~20 min (IN +5%, NJ +14%, LA -48%, party coding in NE/OR); used only CT (exact match to state total)")

TERR = {"60", "66", "69", "72", "78"}
manual = out / "countypres_2000-2024.csv"
frames = []
if manual.exists():
    # Official MEDSL 2000-2024 file (manual download). Use TOTAL mode where present, else sum modes.
    m = pd.read_csv(manual, dtype={"county_fips": str})
    m = m[m["county_fips"].notna()]
    m["fips"] = m["county_fips"].str.zfill(5)
    k = ["year", "fips"]
    has_total = m["mode"].eq("TOTAL").groupby([m.year, m.fips]).transform("any")
    m = m[~has_total | m["mode"].eq("TOTAL")]
    m["rep"] = m["candidatevotes"].where(m["party"].eq("REPUBLICAN"), 0)
    m["dem"] = m["candidatevotes"].where(m["party"].eq("DEMOCRAT"), 0)
    g = m.groupby(k).agg(rep_votes=("rep", "sum"), dem_votes=("dem", "sum"), total_votes=("candidatevotes", "sum")).reset_index()
    g["source"] = "MEDSL countypres_2000-2024 (Dataverse)"
    frames.append(g)
else:
    m = pd.read_csv(out / "countypres_2000-2016.csv")
    n_nofips = m["FIPS"].isna().sum()
    m = m[m["FIPS"].notna()].copy()
    m["fips"] = m["FIPS"].astype(int).astype(str).str.zfill(5)
    # MEDSL codes Kansas City, MO (its own election authority, inside Jackson County) as bogus
    # FIPS 36000; its votes are NOT in the Jackson row for 2004-2016 (2000 KC row is empty,
    # already in Jackson). Fold into Jackson County 29095.
    m.loc[(m["fips"] == "36000") & (m["state_po"] == "MO"), "fips"] = "29095"
    m["rep"] = m["candidatevotes"].where(m["party"].eq("republican"), 0)
    m["dem"] = m["candidatevotes"].where(m["party"].eq("democrat"), 0)
    g = m.groupby(["year", "fips"]).agg(rep_votes=("rep", "sum"), dem_votes=("dem", "sum"),
                                        total_votes=("candidatevotes", "sum")).reset_index()
    g["source"] = "MEDSL county-returns GitHub 2000-2016"
    frames.append(g)
    for y in (2020, 2024):
        t = pd.read_csv(out / f"tonmcg/{y}_US_County_Level_Presidential_Results.csv", dtype={"county_fips": str})
        t = pd.DataFrame({"year": y, "fips": t["county_fips"].str.zfill(5), "rep_votes": t["votes_gop"],
                          "dem_votes": t["votes_dem"], "total_votes": t["total_votes"],
                          "source": "tonmcg GitHub (Fox/Politico/NYT compilation)"})
        if y == 2024:
            # replace CT planning regions with legacy counties from MEDSL official precincts
            t = t[t["fips"].str[:2] != "09"]
            with zipfile.ZipFile(out / "precinct_2024/ct24.zip") as z:
                ct = pd.read_csv(z.open("ct24.csv"), dtype=str)
            ct = ct[(ct["office"] == "US PRESIDENT") & (ct["mode"] == "TOTAL")].copy()
            ct["v"] = pd.to_numeric(ct["votes"])
            ct["rep"] = ct["v"].where(ct["candidate"].str.contains("TRUMP"), 0)
            ct["dem"] = ct["v"].where(ct["candidate"].str.contains("HARRIS"), 0)
            ctg = ct.groupby("county_fips").agg(rep_votes=("rep", "sum"), dem_votes=("dem", "sum"),
                                                total_votes=("v", "sum")).reset_index()
            ctg = ctg.rename(columns={"county_fips": "fips"}).assign(year=2024, source="MEDSL 2024 precinct (CT, TOTAL mode)")
            t = pd.concat([t, ctg], ignore_index=True)
        frames.append(t)

df = pd.concat(frames, ignore_index=True)
# tonmcg 2024 reports DC by ward (pseudo-FIPS 11001-11008) -> one DC row 11001
dc = df["fips"].str[:2] == "11"
dcg = df[dc].groupby("year").agg(rep_votes=("rep_votes", "sum"), dem_votes=("dem_votes", "sum"),
                                 total_votes=("total_votes", "sum"), source=("source", "first")).reset_index()
df = pd.concat([df[~dc], dcg.assign(fips="11001")], ignore_index=True)
# drop empty rows (e.g. 51515 Bedford city 2016 after its 2013 merger into Bedford County)
n_empty = int((df["total_votes"] <= 0).sum())
df = df[df["total_votes"] > 0]
n0 = len(df)
df = df[~df["fips"].str[:2].isin(TERR)]
n_terr = n0 - len(df)

# Alaska -> one statewide row per year
ak = df[df["fips"].str[:2] == "02"]
n_ak_rows = len(ak)
akg = ak.groupby("year").agg(rep_votes=("rep_votes", "sum"), dem_votes=("dem_votes", "sum"),
                             total_votes=("total_votes", "sum"), source=("source", "first")).reset_index()
akg["fips"] = "02000"
df = pd.concat([df[df["fips"].str[:2] != "02"].assign(geo_level="county"), akg.assign(geo_level="state")], ignore_index=True)
df["rep_share"] = df["rep_votes"] / df["total_votes"]
df["rep_share_2p"] = df["rep_votes"] / (df["rep_votes"] + df["dem_votes"])
df = df.sort_values(["year", "fips"])
assert not df.duplicated(["year", "fips"]).any()
df = df[["fips", "year", "rep_votes", "dem_votes", "total_votes", "rep_share", "rep_share_2p", "source", "geo_level"]]
df.to_parquet(CLEAN / "pres_county.parquet", index=False)

# ---- sanity checks
nat = df.groupby("year")[["rep_votes", "dem_votes", "total_votes"]].sum()
nat["R_share_total"] = nat.rep_votes / nat.total_votes
nat["R_share_2party"] = nat.rep_votes / (nat.rep_votes + nat.dem_votes)
nat["n_units"] = df.groupby("year").size()
print(nat.round(4).to_string())

# 2024 state-level check vs MEDSL official state file
st = pd.read_csv(out / "2024-president-state.csv")
st = st[(st["mode"] == "TOTAL") & ~st["state_fips"].astype(str).str.zfill(2).isin(TERR)]
st["fips2"] = st["state_fips"].astype(str).str.zfill(2)
off = st.assign(r=st.votes.where(st.candidate.str.contains("TRUMP"), 0)).groupby("fips2").agg(r=("r", "sum"), tot=("totalvotes", "first"))
ours = df[df.year == 2024].assign(fips2=lambda d: d.fips.str[:2]).groupby("fips2")[["rep_votes", "total_votes"]].sum()
chk = ours.join(off)
chk["d_rep"] = chk.rep_votes / chk.r - 1
chk["d_tot"] = chk.total_votes / chk.tot - 1
bad24 = chk[(chk.d_rep.abs() > 0.01) | (chk.d_tot.abs() > 0.02)]
chk24 = ("2024 vs MEDSL official state totals (official totalvotes includes under/over-votes in some states): "
         "max |d_rep| %.4f, max |d_tot| %.4f; states off >1%%/2%%: %s"
         % (chk.d_rep.abs().max(), chk.d_tot.abs().max(), bad24.round(4).to_dict("index")))
print(chk24)

# 2016 tonmcg vs MEDSL county-level
t16 = pd.read_csv(out / "tonmcg/2016_US_County_Level_Presidential_Results.csv", dtype={"combined_fips": str})
t16["fips"] = t16["combined_fips"].str.zfill(5)
t16 = t16[t16.fips.str[:2] != "02"].drop_duplicates("fips")
cmp16 = df[df.year == 2016].merge(t16[["fips", "per_gop"]], on="fips")
diff16 = (cmp16.rep_share - cmp16.per_gop).abs()
chk16 = (f"2016 tonmcg vs MEDSL rep share: {len(cmp16)} counties, median |diff| {diff16.median():.5f}, "
         f"share >1pp {(diff16 > .01).mean():.4f}")
print(chk16)

ct_fips = {y: sorted(df[(df.year == y) & (df.fips.str[:2] == "09")].fips) for y in df.year.unique()}
msg = (f"pres_county: {len(df)} rows; years {sorted(df.year.unique())}; dropped {n_terr} territory rows, {n_empty} zero-vote rows; KC MO folded into 29095; DC wards (2024) -> 11001; "
       f"AK {n_ak_rows} district rows -> 1 statewide row/year (fips 02000); "
       f"national R share of total: " + ", ".join(f"{y}={v:.4f}" for y, v in nat.R_share_total.items()))
print(msg)
print("CT fips by year:", {int(k): (v[0], v[-1], len(v)) for k, v in ct_fips.items()})
progress(msg)

write_source_md(out, f"""
# County presidential returns 2000-2024

Access date: {today()}

## Intended source (FAILED)
MEDSL County Presidential Returns 2000-2024, Harvard Dataverse doi:10.7910/DVN/VOQCHQ (v20.0, CC0).
File id 13573089 (countypres_2000-2024.tab). The access API returns "You may not download this file
without the required Guestbook response for guestbookID 458". Not submitted on the user's behalf.
Manual download -> save as data/raw/medsl/countypres_2000-2024.csv and rerun code/22_pull_elections.py.

## Sources used
- {URLS['countypres_2000-2016.csv']} (MEDSL, official state data, version 20190722; 2000-2016)
- {URLS['2024-president-state.csv']} (MEDSL official 2024 state totals, used for validation)
- {URLS['precinct_2024/ct24.zip']} (MEDSL official 2024 CT precinct returns; legacy county FIPS)
- tonmcg/US_County_Level_Election_Results_08-24 (MIT licence; NOT authoritative -- compiled by the repo
  author from Fox News, Politico, NYT result pages): 2016 (check only), 2020, 2024 files under tonmcg/.

## Geography
- CT: 2000-2020 legacy counties; 2024 legacy counties from MEDSL precincts (tonmcg's planning-region
  rows dropped).
- AK: reported by state-house district in every source -> collapsed to one statewide row 02000.
- Native county FIPS otherwise (e.g. 51515 Bedford city, 46113 Shannon in early years; 2020/24
  as in tonmcg).
- Precinct files for other states were downloaded during exploration but deleted (not used).

## Result
{msg}

## Checks
- {chk24}
- {chk16}

National totals by year:

{nat.round(4).to_markdown()}
""")
