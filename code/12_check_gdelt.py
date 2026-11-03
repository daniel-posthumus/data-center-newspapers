"""Check whether the BigQuery CLI (`bq`) is installed and authenticated, for GDELT GKG access.
Does NOT set up auth/billing and does NOT run any query (queries cost money)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import OUTLOGS, log_failure, progress, today  # noqa: E402


def main():
    lines = [f"GDELT/BigQuery availability check {today()}"]
    bq = shutil.which("bq")
    gcloud = shutil.which("gcloud")
    lines.append(f"which bq: {bq}")
    lines.append(f"which gcloud: {gcloud}")
    if not bq:
        log_failure("GDELT GKG (BigQuery)", "bq CLI", "bq not installed on this machine; no query attempted")
        lines.append("RESULT: bq not installed -> unusable. Logged failure; stopping.")
    else:
        try:
            r = subprocess.run([bq, "ls"], capture_output=True, text=True, timeout=60)
            ok = r.returncode == 0
            lines.append(f"bq ls returncode={r.returncode}")
            lines.append(f"stdout: {r.stdout[:500]}")
            lines.append(f"stderr: {r.stderr[:500]}")
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f"bq ls error: {e}")
        if ok:
            lines.append("RESULT: bq installed and `bq ls` succeeded -> BigQuery usable. No query run (costs money).")
        else:
            log_failure("GDELT GKG (BigQuery)", "bq ls", "bq installed but not authenticated/usable; did not set up auth")
            lines.append("RESULT: bq present but `bq ls` failed -> unusable. Logged failure.")
    (OUTLOGS / "12_check_gdelt.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    progress("12_check_gdelt: " + lines[-1])


if __name__ == "__main__":
    main()
