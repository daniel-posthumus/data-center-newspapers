# Data failures

| date | source | what | why |
|---|---|---|---|
| 2026-11-03 | Census API (api.census.gov) | CBP / ACS via API | keyless requests redirect to missing_key.html (HTTP 302); used bulk files on www2.census.gov instead. Free key would help. |
| 2026-11-03 | FCC LMS public database | enterpriseefiling.fcc.gov LMS dump/page | HTTP 403 to scripted requests; used frozen CDBS facility.zip (2024-01-09) instead |
| 2026-11-03 | GDELT GKG (BigQuery) | bq CLI | bq not installed on this machine; no query attempted |
| 2026-11-03 | MEDSL county pres 2000-2024 (Dataverse doi:10.7910/DVN/VOQCHQ) | file 13573089 via access API | requires Guestbook response (guestbookID 458) - not submitted on user's behalf; used MEDSL GitHub 2000-16 + tonmcg 2020/2024 (+MEDSL CT precincts 2024). Manual download -> data/raw/medsl/countypres_2000-2024.csv |
| 2026-11-03 | MEDSL 2024 precinct returns (GitHub) | aggregate all states' precincts to county for 2024 | state totals did not reconcile in ~20 min (IN +5%, NJ +14%, LA -48%, party coding in NE/OR); used only CT (exact match to state total) |
| 2026-11-03 | USDA NASS QuickStats API | county ag land value $/acre | API requires free key (keyless HTTP 401); used keyless bulk file qs.economics_*.txt.gz instead |
| 2026-11-03 | Data Center Watch | project-level list after Q1 2025 | no free download; only the 2023-Q1 2025 report PDF has a 16-project list; later reports are paid ($250/$2,500); map/API not used |
| 2026-11-03 | FCC National Broadband Map | county Summary by Geography (BDC) | broadbandmap.fcc.gov returned 403 (Access Denied) to scripted requests; public BDC API needs registered username+token. Fell back to Form 477 June 2021 area table (opendata.fcc.gov xvwq-qtaj) |
| 2026-11-03 | CBP ZIP Code Business Patterns (place-level news) | zbp23detail.zip NAICS 511110 | only 243 ZIP cells published, all with >=3 establishments (same <3 suppression as county CBP from 2017); QCEW has no place/ZIP level -> place-level news supply not constructible from public counts |
| 2026-11-03 | EIA-861 | utility price for TX wires-only utilities (Oncor 44372, CenterPoint 8901, AEP Texas 20404/3278) | ERCOT delivery-only utilities have no rows in Sales_Ult_Cust 'States' (competitive retail), so no utility price; 300 facilities unmatched; use county price instead |
| 2026-11-03 | HIFLD Electric Substations | national substations layer (HIFLD Open / ArcGIS) | no public HIFLD substations service found (only partial third-party AGOL copies, e.g. 2018 FEMA copy 47k pts); EIA Energy Atlas has no substation layer; used OSM power=substation via Overpass |
| 2026-11-03 | LoC newspaper directory | pages [('national_2000_2026', 37)] | request failed after retries |
| 2026-11-03 | LoC Directory of U.S. Newspapers (loc.gov JSON) | full 159,085-title pull | pages ~100s each with frequent IncompleteRead at robots Crawl-Delay 5 (~4h); pulled national dates=2000/2026 subset (23,686) + all TX + all VA instead. End years rarely updated (6.1% of post-2000-active titles have a real end year; known closures e.g. Youngstown Vindicator 2019 still Current) -> not used as closure measure |
