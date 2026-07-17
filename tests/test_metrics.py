"""Unit tests for evaluation/metrics.py — EX semantics + the permutations-blowup fix.

EX spec under test (metrics.py docstring): gold = minimal projection; prediction
may carry EXTRA columns; row-to-row correlation preserved; row order ignored
unless order_matters.
"""
import time

import pandas as pd
import pytest

from evaluation.metrics import execution_match, exact_match


def df(cols: dict) -> pd.DataFrame:
    return pd.DataFrame(cols)


GOLD = df({"state": ["Gujarat", "Kerala", "Bihar"], "total": [5000, 3200, 1800]})


class TestExecutionMatchSemantics:
    def test_identical_frames_match(self):
        assert execution_match(GOLD, GOLD.copy())

    def test_extra_columns_still_match(self):
        pred = df({
            "state_name": ["Gujarat", "Kerala", "Bihar"],
            "gstin_count": [4, 2, 3],
            "total_tds": [5000, 3200, 1800],
            "avg": [1250.0, 1600.0, 600.0],
        })
        assert execution_match(GOLD, pred)

    def test_column_order_swapped_matches(self):
        pred = df({"t": [5000, 3200, 1800], "s": ["Gujarat", "Kerala", "Bihar"]})
        assert execution_match(GOLD, pred)

    def test_row_order_ignored_by_default(self):
        pred = df({"s": ["Bihar", "Gujarat", "Kerala"], "t": [1800, 5000, 3200]})
        assert execution_match(GOLD, pred)

    def test_row_correlation_preserved(self):
        # same value multisets per column, but values swapped ACROSS rows -> no match
        pred = df({"s": ["Gujarat", "Kerala", "Bihar"], "t": [3200, 5000, 1800]})
        assert not execution_match(GOLD, pred)

    def test_fewer_columns_fail(self):
        pred = df({"s": ["Gujarat", "Kerala", "Bihar"]})
        assert not execution_match(GOLD, pred)

    def test_wrong_values_fail(self):
        pred = df({"s": ["Gujarat", "Kerala", "Bihar"], "t": [5000, 3200, 9999]})
        assert not execution_match(GOLD, pred)

    def test_row_count_mismatch_fails(self):
        pred = df({"s": ["Gujarat", "Kerala"], "t": [5000, 3200]})
        assert not execution_match(GOLD, pred)

    def test_none_inputs_fail(self):
        assert not execution_match(None, GOLD)
        assert not execution_match(GOLD, None)

    def test_empty_results_match(self):
        assert execution_match(df({"a": []}), df({"b": []}))

    def test_float_rounding_absorbed(self):
        pred = df({"s": ["Gujarat", "Kerala", "Bihar"], "t": [5000.001, 3199.999, 1800.0]})
        assert execution_match(GOLD, pred)

    def test_string_padding_absorbed(self):
        pred = df({"s": ["Gujarat  ", " Kerala", "Bihar"], "t": [5000, 3200, 1800]})
        assert execution_match(GOLD, pred)

    def test_null_vs_value_fails(self):
        pred = df({"s": ["Gujarat", "Kerala", "Bihar"], "t": [5000, 3200, None]})
        assert not execution_match(GOLD, pred)


class TestOrderMatters:
    def test_exact_order_matches(self):
        assert execution_match(GOLD, GOLD.copy(), order_matters=True)

    def test_reordered_rows_fail_when_order_matters(self):
        pred = df({"s": ["Bihar", "Gujarat", "Kerala"], "t": [1800, 5000, 3200]})
        assert not execution_match(GOLD, pred, order_matters=True)

    def test_extra_columns_ok_when_order_matters(self):
        pred = df({
            "extra": [1, 2, 3],
            "s": ["Gujarat", "Kerala", "Bihar"],
            "t": [5000, 3200, 1800],
        })
        assert execution_match(GOLD, pred, order_matters=True)


class TestPermutationsBlowupFix:
    """Regression for the review-flagged hang: SELECT * (145 cols) vs narrow gold
    used to enumerate npred!/(npred-ng)! ~ 3M+ permutations."""

    def test_wide_prediction_fast_positive(self):
        n = 150
        wide = {f"c{i}": [i * 10 + r for r in range(5)] for i in range(n)}
        wide["state"] = ["A", "B", "C", "D", "E"]
        wide["total"] = [1, 2, 3, 4, 5]
        gold = df({"state": ["A", "B", "C", "D", "E"], "total": [1, 2, 3, 4, 5]})
        t0 = time.monotonic()
        assert execution_match(gold, df(wide))
        assert time.monotonic() - t0 < 1.0

    def test_wide_prediction_fast_negative(self):
        # worst case for the old code: NO combination matches -> full enumeration
        n = 150
        wide = {f"c{i}": [i * 10 + r for r in range(5)] for i in range(n)}
        gold = df({"state": ["A", "B", "C", "D", "E"], "total": [1, 2, 3, 4, 5]})
        t0 = time.monotonic()
        assert not execution_match(gold, df(wide))
        assert time.monotonic() - t0 < 1.0

    def test_duplicate_prediction_columns(self):
        pred = df({
            "a": ["Gujarat", "Kerala", "Bihar"],
            "b": ["Gujarat", "Kerala", "Bihar"],
            "t": [5000, 3200, 1800],
        })
        assert execution_match(GOLD, pred)

    def test_gold_duplicate_columns_need_distinct_pred_columns(self):
        # gold repeats a column; prediction has it only once -> cannot match
        # (matches old permutations semantics: a pred column is used at most once)
        gold = df({"a": [1, 2], "b": [1, 2]})
        pred = df({"x": [1, 2], "y": [9, 9]})
        assert not execution_match(gold, pred)
        pred_ok = df({"x": [1, 2], "y": [1, 2]})
        assert execution_match(gold, pred_ok)

    def test_same_named_prediction_columns(self):
        # SELECT a, a produces two columns with the SAME name; pandas df[name]
        # then returns a DataFrame, which crashed _cols before the iloc fix
        gold = df({"g": [1, 2]})
        pred = pd.DataFrame([[1, 1], [2, 2]], columns=["a", "a"])
        assert execution_match(gold, pred)


class TestExactMatch:
    def test_whitespace_and_case_normalized(self):
        assert exact_match("SELECT  a FROM t;", "select a\nfrom t")

    def test_punctuation_spacing_normalized(self):
        assert exact_match("SELECT SUM( x ) FROM t", "select sum(x) from t")

    def test_different_sql_fails(self):
        assert not exact_match("SELECT a FROM t", "SELECT b FROM t")

    def test_empty(self):
        assert not exact_match("", "SELECT 1") or not exact_match("SELECT 1", "")
