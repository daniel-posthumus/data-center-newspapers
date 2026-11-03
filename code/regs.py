"""Regression helpers (pyfixest) shared by 41-46."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyfixest as pf


def tidy(m, var: str, **meta) -> pd.DataFrame:
    """One row for coefficient `var` of a fitted pyfixest model."""
    co = m.coef()
    if var not in co.index:
        row = dict(term=var, coef=np.nan, se=np.nan, p=np.nan, n=int(m._N))
    else:
        row = dict(term=var, coef=float(co[var]), se=float(m.se()[var]), p=float(m.pvalue()[var]), n=int(m._N))
        # PPML with sparse outcomes can hit (quasi-)separation: implausibly large coefficients with
        # tiny SEs. Flag rather than report as a finding.
        if abs(row["coef"]) > 8 or (row["se"] < 0.01 * abs(row["coef"]) and abs(row["coef"]) > 2):
            row["flag"] = "SUSPECT: likely separation / non-convergence"
    row.update(meta)
    return pd.DataFrame([row])


def stars(p):
    return "" if pd.isna(p) else ("***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else "")


def fit(fml: str, data: pd.DataFrame, kind: str = "ols", cluster: str = "fips"):
    """Fit OLS (feols) or Poisson PPML (fepois) with clustered SEs. Returns (model, error string)."""
    try:
        if kind == "pois":
            m = pf.fepois(fml, data=data, vcov={"CRV1": cluster})
        else:
            m = pf.feols(fml, data=data, vcov={"CRV1": cluster})
        return m, None
    except Exception as e:  # noqa
        return None, repr(e)[:200]


def run_specs(specs, data, terms, kind="ols", cluster="fips", **meta):
    """specs: list of (label, formula). Returns long table; failed fits are recorded, not dropped."""
    out = []
    for lab, fml in specs:
        m, err = fit(fml, data, kind, cluster)
        for t in terms:
            if m is None:
                r = pd.DataFrame([dict(term=t, coef=np.nan, se=np.nan, p=np.nan, n=np.nan, spec=lab,
                                       note=f"NOT RUN/FAILED: {err}")])
            else:
                r = tidy(m, t, spec=lab, note="")
                if "flag" in r:
                    r["note"] = r.pop("flag")
            for k, v in meta.items():
                r[k] = v
            r["formula"] = fml
            r["cluster"] = cluster
            out.append(r)
    return pd.concat(out, ignore_index=True)


def wide(tab: pd.DataFrame, cols="spec", fmt="{:.4f}") -> pd.DataFrame:
    """coef (se) with stars, one column per spec; rows = term; adds N row."""
    t = tab.copy()
    t["cell"] = [("NA" if pd.isna(c) else fmt.format(c) + stars(p) + "\n(" + fmt.format(s) + ")")
                 for c, s, p in zip(t.coef, t.se, t.p)]
    t["cell"] = t.cell.str.replace("\n", " ")
    if "note" in t:
        t.loc[t.note.fillna("").str.startswith("SUSPECT"), "cell"] += " [suspect]"
    order = list(dict.fromkeys(t[cols]))
    w = t.pivot_table(index="term", columns=cols, values="cell", aggfunc="first")[order]
    n = t.groupby(cols, sort=False).n.first().reindex(order)
    w.loc["N"] = [("" if pd.isna(x) else f"{int(x)}") for x in n]
    return w.reset_index()
