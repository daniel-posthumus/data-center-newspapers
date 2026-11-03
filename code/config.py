"""Shared paths and helpers.

All data (raw and clean) lives in Dropbox, not in the repo:
    DATA_DIR = ~/Library/CloudStorage/Dropbox/data-centers-newspaper/data
Override with the environment variable DCN_DATA_DIR. The repo also has a
symlink `data -> DATA_DIR` for convenience (git-ignored).
Results (tables, logs, figures, memo) live in the repo.
"""
from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA_DIR = Path(
    os.environ.get(
        "DCN_DATA_DIR",
        Path.home() / "Library/CloudStorage/Dropbox/data-centers-newspaper/data",
    )
)
RAW = DATA_DIR / "raw"
CLEAN = DATA_DIR / "clean"
INTER = DATA_DIR / "intermediate"

OUT = REPO / "output"
TABLES = OUT / "tables"
OUTLOGS = OUT / "logs"
FIGS = REPO / "memo" / "figures"
LOGS = REPO / "logs"

for _p in (RAW, CLEAN, INTER, TABLES, OUTLOGS, FIGS, LOGS):
    _p.mkdir(parents=True, exist_ok=True)

ATERIO_CSV = RAW / "aterio" / "2026-06-30" / "data_center_inventory_20260630.csv"

UA = {"User-Agent": "Mozilla/5.0 (research data pull; data-center-newspapers)"}


def today() -> str:
    return _dt.date.today().isoformat()


def write_source_md(src_dir: Path, text: str) -> None:
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "SOURCE.md").write_text(text.strip() + "\n")


def log_failure(source: str, what: str, why: str) -> None:
    """Append to logs/data_failures.md (idempotent by exact line)."""
    f = LOGS / "data_failures.md"
    if not f.exists():
        f.write_text("# Data failures\n\n| date | source | what | why |\n|---|---|---|---|\n")
    line = f"| {today()} | {source} | {what} | {why} |\n"
    if line not in f.read_text():
        with f.open("a") as fh:
            fh.write(line)


def progress(msg: str) -> None:
    f = LOGS / "progress.md"
    if not f.exists():
        f.write_text("# Progress log\n\n")
    with f.open("a") as fh:
        fh.write(f"- {_dt.datetime.now():%Y-%m-%d %H:%M} — {msg}\n")


def md_table(df, floatfmt=".3f", index=False) -> str:
    return df.to_markdown(index=index, floatfmt=floatfmt)


def save_table(df, name: str, index=False, floatfmt=".3f") -> None:
    """Write CSV + markdown version of a table to output/tables."""
    df.to_csv(TABLES / f"{name}.csv", index=index)
    (TABLES / f"{name}.md").write_text(md_table(df, floatfmt=floatfmt, index=index) + "\n")
