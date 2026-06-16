"""Evaluation metrics for Text-to-SQL.

Three metrics (thesis):
- VER (Valid Execution Rate): does the predicted SQL run without error?
- EX  (Execution Accuracy):   does the predicted SQL return the SAME result set
                              as the gold SQL? Primary metric.
- EM  (Exact Match):          normalized string equality of predicted vs gold SQL
                              (strict; expected low — reported for completeness).

EX definition (documented so the thesis can state it precisely):
- Both queries are executed; results are compared as a MULTISET of rows.
- Cell values are normalized: Decimal/float rounded to 2 dp, strings trimmed,
  None preserved. This absorbs float noise and padding.
- Row order is IGNORED by default (rows are sorted before comparison) because
  most questions are not inherently ordered. For questions whose answer IS an
  ordering ("top N", "rank"), set order_matters=True on the gold item and the
  comparison becomes order-sensitive.
- Gold SQL is authored to the MINIMAL projection that answers the question. The
  prediction may return EXTRA columns (e.g. an added trade-name label) and still
  match: EX passes iff some ordered selection of the prediction's columns equals
  gold's rows. Row-to-row correlation is preserved (whole rows are projected, not
  columns compared independently), so swapping values across rows does NOT match.
  Column ORDER is therefore tolerated; column COUNT may be >= gold's.
"""
from __future__ import annotations

import re
from decimal import Decimal
from itertools import permutations

import pandas as pd


def _norm_cell(v: object) -> object:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (Decimal, float, int)) and not isinstance(v, bool):
        return round(float(v), 2)
    return str(v).strip()


def _cols(df: pd.DataFrame) -> list[list]:
    return [[_norm_cell(v) for v in df[c].tolist()] for c in df.columns]


def execution_match(
    gold_df: pd.DataFrame | None,
    pred_df: pd.DataFrame | None,
    order_matters: bool = False,
) -> bool:
    """EX: does some column-selection of the prediction reproduce gold's rows?"""
    if gold_df is None or pred_df is None:
        return False
    ng, npred = gold_df.shape[1], pred_df.shape[1]
    if npred < ng or len(gold_df) != len(pred_df):
        return False
    gcols, pcols = _cols(gold_df), _cols(pred_df)
    gold_rows = list(zip(*gcols)) if gcols else []
    for combo in permutations(range(npred), ng):
        pred_rows = list(zip(*[pcols[c] for c in combo]))
        if order_matters:
            if pred_rows == gold_rows:
                return True
        elif sorted(gold_rows, key=repr) == sorted(pred_rows, key=repr):
            return True
    return False


def _norm_sql(sql: str) -> str:
    if not sql:
        return ""
    s = sql.strip().rstrip(";").lower()
    s = re.sub(r"\s+", " ", s)            # collapse whitespace
    s = re.sub(r"\s*([(),])\s*", r"\1", s)  # tighten around punctuation
    return s.strip()


def exact_match(gold_sql: str, pred_sql: str) -> bool:
    """EM: normalized string equality (strict)."""
    return _norm_sql(gold_sql) == _norm_sql(pred_sql)
