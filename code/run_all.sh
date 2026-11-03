#!/usr/bin/env bash
# Run the full pipeline end to end. Data are read/written in Dropbox (see code/config.py).
# Download steps are idempotent (skip files already present).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
for s in 00_profile_aterio 00b_download_geo_pop 01a_download_cbp 01b_clean_cbp 02a_download_qcew 02b_clean_qcew \
         03_build_population 04_build_news_panel 05_build_aterio_campus 06_overlap_power \
         10_pull_loc_directory 11_pull_fcc_broadcast 12_check_gdelt 13_check_datacenterwatch 14_profile_aterio_links \
         20_pull_acs 21_pull_rucc 22_pull_elections 23_pull_cog 24_pull_nass_landvalue \
         30_pull_grid_infra 31_pull_eia861 32_pull_aqueduct 33_pull_broadband \
         40_build_analysis_data 41_measurement 42_descriptives 43_extensive 44_intensive 45_secrecy 46_placebos \
         50_build_memo; do
  echo "=== $s"; $PY -W ignore code/$s.py
done
