"""Unit tests for core/sql_validator.py — SELECT-only enforcement, injection
blocking, CTE handling, and the allow-list table extraction (incl. the
review-flagged comma-FROM bypass)."""
import pytest

from core.sql_validator import validate_sql, _extract_table_names
import sqlparse


ALLOWED = {
    "public.tbl_ewb_parta_ewb", "public.tbl_gst_rtn_r7", "public.tbl_gst_rtn_r7_tds",
    "live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned",
    "common.mst_fy_years_t", "common.mst_3bd_months_t",
}


def tables_of(sql: str) -> set[str]:
    return _extract_table_names(sqlparse.parse(sql)[0])


class TestSelectOnly:
    def test_plain_select_passes(self):
        assert validate_sql("SELECT COUNT(*) FROM public.tbl_ewb_parta_ewb;", ALLOWED).valid

    def test_empty_rejected(self):
        assert not validate_sql("", ALLOWED).valid
        assert not validate_sql("   ", ALLOWED).valid

    def test_delete_rejected(self):
        assert not validate_sql("DELETE FROM public.tbl_gst_rtn_r7", ALLOWED).valid

    def test_update_rejected(self):
        assert not validate_sql("UPDATE public.tbl_gst_rtn_r7 SET fp='x'", ALLOWED).valid

    def test_injection_second_statement_rejected(self):
        assert not validate_sql(
            "SELECT 1; DROP TABLE public.tbl_gst_rtn_r7", ALLOWED).valid

    def test_trailing_semicolon_ok(self):
        assert validate_sql("SELECT 1;", None).valid

    def test_cte_hiding_delete_rejected(self):
        assert not validate_sql(
            "WITH x AS (SELECT 1) DELETE FROM public.tbl_gst_rtn_r7", ALLOWED).valid

    def test_cte_select_passes(self):
        sql = ("WITH t AS (SELECT gstin FROM public.tbl_gst_rtn_r7) "
               "SELECT COUNT(*) FROM t")
        assert validate_sql(sql, ALLOWED).valid


class TestAllowList:
    def test_unknown_table_rejected(self):
        res = validate_sql("SELECT * FROM public.hallucinated_table", ALLOWED)
        assert not res.valid
        assert "hallucinated_table" in res.error

    def test_join_tables_all_checked(self):
        res = validate_sql(
            "SELECT * FROM public.tbl_gst_rtn_r7 r JOIN public.evil e ON r.gstin = e.g",
            ALLOWED)
        assert not res.valid

    def test_comma_from_second_table_checked(self):
        # regression: 'FROM a, b' used to extract only 'a' -> allow-list bypass
        res = validate_sql(
            "SELECT * FROM public.tbl_gst_rtn_r7, public.secret_table", ALLOWED)
        assert not res.valid
        assert "secret_table" in res.error

    def test_comma_from_with_aliases(self):
        assert tables_of(
            "SELECT * FROM public.tbl_gst_rtn_r7 r, public.tbl_gst_rtn_r7_tds t "
            "WHERE t.tbl_gst_rtn_r7 = r.id"
        ) == {"public.tbl_gst_rtn_r7", "public.tbl_gst_rtn_r7_tds"}

    def test_comma_from_three_tables(self):
        assert tables_of("SELECT 1 FROM a, b, c WHERE a.x = b.y") == {"a", "b", "c"}

    def test_select_list_commas_not_tables(self):
        assert tables_of(
            "SELECT gstin, fp, ret_period FROM public.tbl_gst_rtn_r7"
        ) == {"public.tbl_gst_rtn_r7"}

    def test_function_arg_commas_not_tables(self):
        assert tables_of(
            "SELECT COALESCE(iamt, 0), ROUND(camt, 2) FROM public.tbl_gst_rtn_r7_tds "
            "WHERE COALESCE(samt, 0) > 0"
        ) == {"public.tbl_gst_rtn_r7_tds"}

    def test_subquery_then_comma_table(self):
        assert tables_of(
            "SELECT * FROM (SELECT gstin FROM public.tbl_gst_rtn_r7 WHERE fp = '042024') s, "
            "common.mst_fy_years_t f"
        ) == {"public.tbl_gst_rtn_r7", "common.mst_fy_years_t"}

    def test_in_list_commas_after_where_not_tables(self):
        assert tables_of(
            "SELECT * FROM public.tbl_gst_rtn_r7 WHERE fp IN ('042024', '052024')"
        ) == {"public.tbl_gst_rtn_r7"}

    def test_schema_qualified_join_pair(self):
        assert tables_of(
            "SELECT * FROM live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned r "
            "JOIN common.mst_fy_years_t f ON r.fy_flag = f.fy_flag "
            "WHERE r.fy_flag = 8"
        ) == {"live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned",
              "common.mst_fy_years_t"}

    def test_order_by_after_from_list_closed(self):
        assert tables_of(
            "SELECT a.x FROM a, b ORDER BY a.x, b.y"
        ) == {"a", "b"}
