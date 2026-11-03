"""50 — Build the memo from memo/memo_template.md.

Placeholders in the template:
  {{tab:NAME}}          -> output/tables/NAME.md inserted verbatim (so every table is a script output)
  {{tab:NAME|cols=a,b}} -> same, keeping only the listed columns (from NAME.csv)
Writes memo/news_deserts_feasibility_memo.md and, if pandoc (pypandoc_binary) and a LaTeX engine are
available, memo/news_deserts_feasibility_memo.pdf.
"""
import re
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import REPO, TABLES, progress

tpl = (REPO / "memo" / "memo_template.md").read_text()


def repl(m):
    name, opts = m.group(1), m.group(2)
    if opts:
        cols = opts.split("=", 1)[1].split(",")
        df = pd.read_csv(TABLES / f"{name}.csv")
        return df[cols].to_markdown(index=False, floatfmt=".3f")
    f = TABLES / f"{name}.md"
    if not f.exists():
        raise FileNotFoundError(f"memo references missing table {name}")
    return f.read_text().strip()


out = re.sub(r"\{\{tab:([A-Za-z0-9_\-]+)(\|cols=[^}]+)?\}\}", repl, tpl)
md = REPO / "memo" / "news_deserts_feasibility_memo.md"
md.write_text(out)
print("wrote", md)

try:
    import pypandoc
    engine = next((e for e in ["xelatex", "pdflatex"] if shutil.which(e)), None)
    if engine is None:
        print("no LaTeX engine; PDF skipped")
    else:
        pdf = md.with_suffix(".pdf")
        # glyphs missing from the PDF font: substitute in a temporary copy used only for the PDF
        tmp = md.with_name("_pdf_build.md")
        tmp.write_text(out.replace("☐", "[ ]").replace("→", "\\ensuremath{\\to}").replace("✓", "Done"))
        args = [f"--pdf-engine={engine}", "--resource-path", str(REPO / "memo"),
                "-V", "geometry:margin=0.75in", "-V", "fontsize=10pt", "-V", "colorlinks=true", "--toc"]
        pypandoc.convert_file(str(tmp), "pdf", outputfile=str(pdf), extra_args=args)
        tmp.unlink()
        print("wrote", pdf)
except Exception as e:  # noqa
    print("PDF build failed:", repr(e)[:500])
progress("50 memo built")
