-- ============================================================
-- Schema: common  |  Module: COMMON MASTER TABLES (shared decode / lookup)
-- (module frame — human doc only; the table comment starts below the blank line)
-- Small 1:1 masters that DECODE coded fact columns into officer-readable labels
-- (fy_flag -> FY label, ret_period -> month/quarter). Never the subject of a
-- question on their own; always LEFT-JOINed to a fact table (r3b flat MV today).
-- ============================================================

-- Financial-year master. flag_fy -> FY label "2024-25" (project desc_year AS
--   financial_year). One row per financial year. Join: flag_fy = <fact>.fy_flag.
-- --- GENERATOR NOTES (generator only) ---
-- To DISPLAY a financial year, LEFT JOIN on flag_fy = <fact>.fy_flag and project
--   desc_year (AS financial_year); keep fy_flag itself for WHERE / GROUP BY /
--   ORDER BY. Always LEFT JOIN — 1:1 lookup, never multiplies fact rows.

CREATE TABLE IF NOT EXISTS common.mst_fy_years_t
(
    flag_fy integer, -- Financial-Year flag. JOIN KEY ↔ <fact>.fy_flag (e.g. r3b MV fy_flag). Sample: 8 (=FY2024-25), 5 (=FY2021-22). Domain 1=FY2017-18 … 11=FY2027-28.
    desc_year character varying(10), -- Financial-year LABEL for display. Sample: "2024-25", "2021-22". ← project THIS (AS financial_year) in place of the raw fy_flag integer.
    desc_year_full character varying(15), -- Verbose FY span label. Sample: "Apr 24-Mar 25".
    desc_year_fl_sql character varying(15), -- FY label in uppercase report style. Sample: "APR24-MAR25" (same vocabulary as mst_3bd_months_t.fy_year).
    fp_desc character varying(10), -- Final return-period (MMYYYY) that closes this FY. Sample: "032025" (March 2025 closes FY2024-25).
    record_status character varying(5), -- Row status. "A" = active, "D" = deleted.
    fy_year_desc character varying, -- Financial year in full four-digit form. Sample: "2024-2025".
    -- flag_fy is 1-row-per-financial-year (unique). Marking it UNIQUE tells the
    -- fan-out detector the decode join (fact.fy_flag = flag_fy) is 1:N, not M:N,
    -- so labelling never trips a false fan-out on COUNT/SUM. (UNIQUE, not PRIMARY
    -- KEY: the live table declares no PK — we assert only that the values are
    -- unique, which is the single fact the detector needs.)
    UNIQUE (flag_fy)
);

-- Return-period (MONTH) master. ret_period_fl -> month name / quarter (project
--   month_desc / quarter). One row per return period. Join: ret_period_fl =
--   <fact>.ret_period (VARCHAR MMYYYY).
-- --- GENERATOR NOTES (generator only) ---
-- To DISPLAY a month/quarter, LEFT JOIN on ret_period_fl = <fact>.ret_period and
--   project month_desc / quarter; keep ret_period for WHERE / GROUP BY / ORDER BY.
--   Always LEFT JOIN — 1:1 lookup. Carries the AUTHORITATIVE month->FY mapping
--   (fy_flag per return period): ret_period '032025' (March 2025) -> fy_flag 8 =
--   FY2024-25, NOT calendar 2025. Use fy_flag for financial-year scoping; never
--   derive FY from the calendar year inside ret_period.
CREATE TABLE IF NOT EXISTS common.mst_3bd_months_t
(
    mnth_id integer, -- Cumulative month counter (chronological across FYs). JOIN KEY ↔ <fact>.mnth_id. Sample: 94 (=Apr 2025), 105 (=Mar 2026). Increments monthly.
    ret_period integer, -- Return period as INTEGER (leading zero DROPPED). Sample: 32026 (=March 2026), 122025 (=Dec 2025). ⚠ Do NOT join on this column — use ret_period_fl (the zero-padded VARCHAR) to match <fact>.ret_period.
    from_date date, -- (low-signal) period-start marker; appears fixed in the source data. Prefer ret_period_fl / to_date for period logic.
    to_date timestamp without time zone, -- Period END (month-end timestamp). Sample: "2026-03-31 23:59:00", "2025-04-30 23:59:00".
    ct integer, -- (internal) sequence counter; not meaningful for officer queries.
    fy_year character varying(20), -- Financial-year label, uppercase report style. Sample: "APR25-MAR26".
    fy_flag integer, -- Financial-Year flag for this return period. ↔ <fact>.fy_flag and mst_fy_years_t.flag_fy. Sample: 9 (=FY2025-26). AUTHORITATIVE month→FY mapping (resolves the calendar-vs-FY boundary).
    record_status character varying(1), -- Row status. "A" = active, "D" = deleted.
    ret_period_fl character varying(10), -- Return period MMYYYY, zero-padded VARCHAR. JOIN KEY ↔ <fact>.ret_period. Sample: "032026" (March 2026), "122025" (Dec 2025).
    month_desc character varying, -- Month NAME for display. Sample: "March", "January", "April". ← project THIS for the month label.
    mnth_cd integer, -- Calendar month number 1–12. Sample: 3 (March), 1 (January), 4 (April). Use for chronological month sort within a financial year.
    quarter character varying, -- GST quarter label, populated ONLY on the quarter's CLOSING month (Jun→"Q1", Sep→"Q2", Dec→"Q3", Mar→"Q4"); blank on the other two months. For an every-row quarter key use quarter_all_mnths.
    quarter_all_mnths character varying, -- Quarter key present on EVERY month: the MMYYYY of the quarter's closing month (Jan/Feb/Mar 2026 all → "032026"). Use to GROUP BY quarter across all three months.
    -- ret_period_fl (the join key to the fact's ret_period) and mnth_id are each
    -- 1-row-per-return-period (unique). Marking them UNIQUE makes the month-decode
    -- join 1:N, not M:N — no false fan-out. (UNIQUE, not PRIMARY KEY: the live
    -- table declares no PK; both are unique candidate keys.)
    UNIQUE (ret_period_fl),
    UNIQUE (mnth_id)
);