"""Profile Aterio link fields PROJECT_PERMIT_URL and DATASHEET_URL (local only; NO web requests).

- share with PROJECT_PERMIT_URL populated (facility and campus level), by state and stage
- top domains in each field (fields are comma-separated multi-URL lists)
- rule-based classification of DATASHEET_URL domains (rules written out below) and share of
  facilities/campuses with >=1 local-news URL
- TX permit URLs pointing to agenda/minutes systems
Outputs: output/tables/aterio_links_*.csv/.md, output/logs/14_profile_aterio_links.txt
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import INTER, OUTLOGS, progress, save_table, today  # noqa: E402

# ---------------------------------------------------------------- classification rules
# Applied in this order; first match wins. Matching is on the domain with 'www.' removed.
PRESS_WIRE = {"prnewswire.com", "businesswire.com", "globenewswire.com", "newswire.ca", "accesswire.com",
              "einpresswire.com", "einnews.com", "send2press.com", "pressranger.com", "app.quotemedia.com", "markets.financialcontent.com"}
SOCIAL_VIDEO = {"youtube.com", "linkedin.com", "x.com", "twitter.com", "facebook.com", "instagram.com",
                "tiktok.com", "reddit.com", "substack.com", "google.com", "onedrive.live.com",
                "citizenportal.ai", "bhamwiki.com", "wikipedia.org"}
NATIONAL_TRADE = {
    # national general/financial press
    "bloomberg.com", "reuters.com", "cnbc.com", "ft.com", "wsj.com", "nytimes.com", "washingtonpost.com",
    "yahoo.com", "finance.yahoo.com", "investing.com", "markets.businessinsider.com", "businessinsider.com",
    "cbsnews.com", "nbcnews.com", "abcnews.go.com", "foxnews.com", "foxbusiness.com", "apnews.com", "axios.com",
    "usatoday.com", "theguardian.com", "politico.com", "thenation.com", "insideclimatenews.org", "npr.org",
    "forbes.com", "fortune.com", "techcrunch.com", "theverge.com", "theinformation.com", "semafor.com",
    # trade press
    "datacenterdynamics.com", "datacenterfrontier.com", "datacenterknowledge.com", "thetechcapital.com",
    "dgtlinfra.com", "bisnow.com", "renewableenergyworld.com", "powermag.com", "world-nuclear-news.org",
    "worldoil.com", "theenergymag.com", "govtech.com", "dezeen.com", "newprojectmedia.com", "commercialsearch.com",
    "utilitydive.com", "datacenterhawk.com", "constructiondive.com", "enr.com", "globest.com", "therecord.media",
    "newsweek.com", "theregister.com", "insurancejournal.com", "theglobeandmail.com", "credaily.com",
    "tomshardware.com", "datacentremagazine.com", "capacitymedia.com", "costar.com", "connectcre.com",
}
REGIONAL_BUSINESS = {"bizjournals.com", "richmondbizsense.com", "virginiabusiness.com", "azbigmedia.com",
                     "elpasoinc.com", "insideindianabusiness.com", "ingrams.com", "businessrecord.com", "biztimes.com", "crainsdetroit.com", "chicagobusiness.com", "crainscleveland.com"}
GOV_PLATFORM = re.compile(r"(\.gov$|\.gov\.|\.mil$|\.us$|\.state\.[a-z]{2}\.us|granicus|legistar|municode|civicplus|"
                          r"civicclerk|civicweb|boarddocs|destinyhosted|tylerhost|novusagenda|agendaonline|iqm2|"
                          r"primegov|escribemeetings|laserfiche|ecode360|edocpub|nyiso|ercot|pjm\.com|miso|"
                          r"pwcgov\.org|luzernecounty\.org|lyon-county\.org|atlantaregional|monroecoga|"
                          r"countyor|county\.org$|countyga|countyva|countytx|cityof)")
# Local / regional news outlets identified by hand from the top-domain list (please check):
LOCAL_NEWS_EXPLICIT = {
    "princewilliamtimes.com", "ksl.com", "thetimes-tribune.com", "sltrib.com", "abc4.com", "amarillotribune.org",
    "dispatch.com", "wrdw.com", "wvia.org", "shawlocal.com", "pennlive.com", "fox56.com", "keranews.org",
    "tri-cityherald.com", "missourian.com", "potomaclocal.com", "kjrh.com", "hillsbororeporter.com",
    "firstalert4.com", "jconline.com", "weku.org", "sciotopost.com", "fredericksburg.com", "wgxa.tv",
    "fredericksburgfreepress.com", "krtv.com", "riverreporter.com", "wnep.com", "abc3340.com", "13wmaz.com",
    "newschannel6now.com", "covnews.com", "komu.com", "mississippitoday.org", "news5cleveland.com",
    "alvareviewcourier.com", "wspynews.com", "fox5atlanta.com", "fox59.com", "dailyjournal.net",
    "chestertontribune.com", "kshb.com", "citizensvoice.com", "olneyenterprise.com", "earlycountynews.com",
    "wsbt.com", "wane.com", "expressnews.com", "wpr.org", "wfmz.com", "fortworthreport.org", "mlive.com",
    "wcpo.com", "mountvernonnews.com", "timesleader.com", "chicagotribune.com", "northernvirginiamag.com",
    "pinalpost.com", "illinoistimes.com", "wdrb.com", "thespec.com", "loudounnow.com", "fox6now.com",
    "kvoa.com", "azluminaria.org", "georgiamediagroup.org", "civicmedia.us", "nwiforum.org", "portwallawalla.com",
    "latimes.com", "ajc.com", "dallasnews.com", "houstonchronicle.com", "statesman.com", "star-telegram.com",
    "richmond.com", "insidenova.com", "loudountimes.com", "wtop.com", "cardinalnews.org", "texastribune.org",
    "dchieftain.com", "nbcphiladelphia.com", "texomashomepage.com", "crossroadstoday.com", "bigcountryhomepage.com",
}
# Generic local-news patterns (applied after the explicit national/trade lists):
TV_CALL = re.compile(r"^(?:[kw][a-z]{2,3}(?:tv|\d{1,2})?|(?:fox|abc|cbs|nbc|news|kare|wfaa)\d{1,3}(?:now|news|online)?"
                     r"|\d{1,2}(?:news|abc|wmaz|wsb)[a-z]*|newschannel\d+[a-z]*|firstalert\d+|wkyc|wral|wsoctv)\."
                     r"(?:com|tv|org|net)$")
PAPER_WORDS = re.compile(r"(times|tribune|herald|gazette|journal|news|post|courier|dispatch|ledger|sentinel|observer|"
                         r"chronicle|register|enterprise|reporter|press|daily|record|bee|eagle|independent|examiner|"
                         r"leader|telegraph|democrat|republican|citizen|messenger|beacon|banner|argus|mirror|"
                         r"monitor|globe|inquirer|patch|voice|tribune|local|courant|statesman|oklahoman|"
                         r"advocate|pilot|progress|current|now)")
COMPANY_HINT = re.compile(r"(datacent|data-?center|\bdc\b|dc\.com$|digital|infra|capital|energy|power|tech|computing|"
                          r"cloud|\.ai$|realty|partners|properties|hyperscale|campus|atmeta|microsoft|amazon|apple\.com|"
                          r"equinix|lumen|cogentco|qts|stack|vantage|edgeconnex|cyrusone|switch\.com|tract\.com|"
                          r"databank|flexential|tierpoint|aligned|crusoe|coreweave|cipher|terawulf|iren|galaxy|"
                          r"corescientific|caterpillar|ntt|ironmountain|expedient|blackstone|sec\.gov|investor|ir\.|"
                          r"hubspot|cloudfront|propertycapsule|mining|nuclear|solar|wind)")


def classify(dom: str) -> str:
    if not dom:
        return "other"
    base = ".".join(dom.split(".")[-2:])
    if dom in PRESS_WIRE or base in PRESS_WIRE:
        return "press_release_wire"
    if dom in SOCIAL_VIDEO or base in SOCIAL_VIDEO or dom.endswith(".substack.com"):
        return "social_video_other_platform"
    if dom in NATIONAL_TRADE or base in NATIONAL_TRADE:
        return "national_or_trade_press"
    if dom in REGIONAL_BUSINESS or base in REGIONAL_BUSINESS:
        return "regional_business_press"
    if dom in LOCAL_NEWS_EXPLICIT or base in LOCAL_NEWS_EXPLICIT:
        return "local_news"
    if base in {"kdc.com", "kpf.com", "sec.gov"}:  # developer / architecture firm / SEC filings
        return "company_site"
    if GOV_PLATFORM.search(dom):
        return "government_agency"
    if TV_CALL.match(base):
        return "local_news"
    if COMPANY_HINT.search(dom):
        return "company_site"
    if PAPER_WORDS.search(base.split(".")[0]):
        return "local_news"
    return "other"


AGENDA = re.compile(r"(granicus|legistar|civicclerk|boarddocs|municode|civicweb|destinyhosted|novusagenda|"
                    r"agendaonline|iqm2|primegov|escribemeetings|agenda|minutes|commissioners.?court|"
                    r"meeting|/council|laserfiche)", re.I)


def split_urls(s) -> list[str]:
    if not isinstance(s, str) or not s.strip():
        return []
    parts = re.split(r",\s*(?=(?:https?://|www\.))", s.strip())
    return [p.strip() for p in parts if p.strip()]


def domain(u: str) -> str:
    if not re.match(r"https?://", u):
        u = "http://" + u
    d = urlparse(u).netloc.lower()
    return d.split("@")[-1].split(":")[0].removeprefix("www.")


def main():
    a = pd.read_parquet(INTER / "aterio_facility.parquet")
    a = a[a["is_us"]].copy()
    a["campus"] = a["ATERIO_DATA_CENTER_CAMPUS_UID"].fillna(a["ATERIO_DATA_CENTER_UID"])
    a["has_permit"] = a["PROJECT_PERMIT_URL"].map(lambda s: len(split_urls(s)) > 0)
    a["has_datasheet"] = a["DATASHEET_URL"].map(lambda s: len(split_urls(s)) > 0)
    camp = a.groupby("campus").agg(state=("STATE_CODE", "first"), has_permit=("has_permit", "max"),
                                   has_datasheet=("has_datasheet", "max"),
                                   stage=("DATA_CENTER_STAGE", lambda s: s.mode().iloc[0] if s.notna().any() else None))
    L = [f"Aterio link profile {today()} — US facilities: {len(a)}, campuses: {len(camp)}"]
    L.append(f"facility share with PROJECT_PERMIT_URL: {a.has_permit.mean():.3f}; campus share: {camp.has_permit.mean():.3f}")
    L.append(f"facility share with DATASHEET_URL: {a.has_datasheet.mean():.3f}; campus share: {camp.has_datasheet.mean():.3f}")

    # by state
    fs = a.groupby("STATE_CODE").agg(n_fac=("has_permit", "size"), fac_share_permit=("has_permit", "mean"))
    cs = camp.groupby("state").agg(n_campus=("has_permit", "size"), campus_share_permit=("has_permit", "mean"))
    bs = fs.join(cs).reset_index().rename(columns={"STATE_CODE": "state"}).sort_values("n_fac", ascending=False)
    save_table(bs, "aterio_links_permit_by_state")
    for s in ("TX", "VA"):
        r = bs[bs.state.eq(s)].iloc[0]
        L.append(f"  {s}: facilities {r.n_fac}, share permit {r.fac_share_permit:.3f}; campuses {r.n_campus}, share {r.campus_share_permit:.3f}")
    # by stage (campus stage = modal facility stage)
    fst = a.groupby("DATA_CENTER_STAGE").agg(n_fac=("has_permit", "size"), fac_share_permit=("has_permit", "mean"))
    cst = camp.groupby("stage").agg(n_campus=("has_permit", "size"), campus_share_permit=("has_permit", "mean"))
    bst = fst.join(cst).reset_index().rename(columns={"DATA_CENTER_STAGE": "stage"})
    save_table(bst, "aterio_links_permit_by_stage")
    L.append("permit share by stage:\n" + bst.to_string(index=False))

    # domains
    rows = []
    for col in ("PROJECT_PERMIT_URL", "DATASHEET_URL"):
        for uid, camp_id, st, s in a[["ATERIO_DATA_CENTER_UID", "campus", "STATE_CODE", col]].itertuples(index=False):
            for u in split_urls(s):
                rows.append((col, uid, camp_id, st, u, domain(u)))
    urls = pd.DataFrame(rows, columns=["field", "uid", "campus", "state", "url", "domain"])
    urls["type"] = urls["domain"].map(classify)
    for col, nm in (("PROJECT_PERMIT_URL", "permit"), ("DATASHEET_URL", "datasheet")):
        u = urls[urls.field.eq(col)]
        top = (u.groupby("domain").agg(n_urls=("url", "size"), n_facilities=("uid", "nunique"),
                                       n_campuses=("campus", "nunique"), type=("type", "first"))
               .sort_values("n_facilities", ascending=False).head(30).reset_index())
        save_table(top, f"aterio_links_top_domains_{nm}")
        L.append(f"{col}: {len(u)} URLs, {u.domain.nunique()} domains")

    ds = urls[urls.field.eq("DATASHEET_URL")]
    # share of facilities (all US, and those with datasheet) with >=1 URL of each type
    typ = ds.groupby(["uid", "type"]).size().unstack(fill_value=0).gt(0)
    typ = typ.reindex(a["ATERIO_DATA_CENTER_UID"], fill_value=False)
    ctyp = ds.groupby(["campus", "type"]).size().unstack(fill_value=0).gt(0).reindex(camp.index, fill_value=False)
    tshare = pd.DataFrame({
        "share_all_us_facilities": typ.mean(),
        "share_facilities_with_datasheet": typ[a.set_index("ATERIO_DATA_CENTER_UID")["has_datasheet"].values].mean(),
        "share_all_us_campuses": ctyp.mean(),
        "n_urls": ds["type"].value_counts(),
    }).reset_index().rename(columns={"index": "type"})
    save_table(tshare, "aterio_links_datasheet_type_shares")
    L.append("datasheet URL type shares (>=1 URL of type):\n" + tshare.to_string(index=False))
    if "local_news" in typ:
        L.append(f"facilities with >=1 local-news datasheet URL: {typ['local_news'].sum()} / {len(typ)} = {typ['local_news'].mean():.3f}")
        L.append(f"campuses with >=1 local-news datasheet URL: {ctyp['local_news'].sum()} / {len(ctyp)} = {ctyp['local_news'].mean():.3f}")
        lr = typ["local_news"] | typ.get("regional_business_press", False)
        L.append(f"facilities with >=1 local-news OR regional-business-press URL: {lr.mean():.3f}")
        for s in ("TX", "VA"):
            m = (a["STATE_CODE"].eq(s)).values
            L.append(f"  {s}: facility share with local-news datasheet URL {typ['local_news'][m].mean():.3f}")
    ln = (ds[ds.type.eq("local_news")].groupby("domain").agg(n_facilities=("uid", "nunique"), n_campuses=("campus", "nunique"),
                                                               states=("state", lambda s: ",".join(sorted(set(s)))))
          .sort_values("n_facilities", ascending=False).reset_index())
    ln["rule"] = ln["domain"].map(lambda d: "explicit" if d in LOCAL_NEWS_EXPLICIT or ".".join(d.split(".")[-2:]) in LOCAL_NEWS_EXPLICIT
                                  else ("tv_callsign_regex" if TV_CALL.match(".".join(d.split(".")[-2:])) else "paper_word_regex"))
    save_table(ln, "aterio_links_local_news_domains")
    L.append(f"distinct domains classified local_news: {len(ln)} (see aterio_links_local_news_domains.csv for human check)")
    oth = ds[ds.type.eq("other")].domain.value_counts().head(40)
    L.append("top 'other' datasheet domains (unclassified): " + ", ".join(f"{k}:{v}" for k, v in oth.items()))

    # TX permit URLs -> agenda / minutes systems
    tx = urls[urls.field.eq("PROJECT_PERMIT_URL") & urls.state.eq("TX")].copy()
    tx["agenda_like"] = tx["url"].str.contains(AGENDA.pattern, case=False, regex=True)
    tx["agenda_system"] = tx["url"].str.extract(AGENDA)[0].str.lower()
    L.append(f"TX permit URLs: {len(tx)} URLs on {tx.uid.nunique()} facilities / {tx.campus.nunique()} campuses")
    L.append(f"  agenda/minutes-like URLs: {tx.agenda_like.sum()} on {tx[tx.agenda_like].uid.nunique()} facilities / "
             f"{tx[tx.agenda_like].campus.nunique()} campuses")
    L.append("  by matched keyword: " + str(tx.loc[tx.agenda_like, "agenda_system"].value_counts().to_dict()))
    txd = (tx.groupby("domain").agg(n_urls=("url", "size"), n_facilities=("uid", "nunique"), n_campuses=("campus", "nunique"),
                                    n_agenda_like=("agenda_like", "sum"))
           .sort_values("n_facilities", ascending=False).reset_index())
    save_table(txd, "aterio_links_tx_permit_domains")
    L.append("  TX permit top domains:\n" + txd.head(25).to_string(index=False))
    (OUTLOGS / "14_profile_aterio_links.txt").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    progress("14_profile_aterio_links: link-field profile tables written (aterio_links_*)")


if __name__ == "__main__":
    main()
