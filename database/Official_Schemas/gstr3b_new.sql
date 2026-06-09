-- ============================================================
-- Schema: live_reports
-- Module: GSTR3B (Monthly Summary Return — DENORMALIZED FLAT VIEW)
-- Description: Single-table comprehensive R3B report. Replaces the 17-table
-- normalized schema in schema/modules/gstr3b.sql for officer-facing queries.
-- DBA-maintained materialized view; refreshed DAILY; partitioned by fy_flag.
-- One row per (gstin, ret_period) — i.e. one row per filed GSTR-3B return.
--
-- Tables (brief):
-- 1) live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned -- MAIN TABLE (and ONLY table). Has gstin, ret_period, geo dims, AND all R3B amounts. JOIN to NOTHING — all R3B data is here on one row.
-- ============================================================
--
-- KEY CONVENTIONS for this module (read before generating SQL):
--   * SINGLE TABLE — never JOIN this table back to any tbl_gst_rtn_r3b* base table.
--   * Geo hierarchy: division → range → unit (NOT division → district → ward).
--   * fil_dt is native DATE — direct date comparisons. Do NOT use TO_DATE().
--   * ret_period is VARCHAR MMYYYY (e.g. '042021' = April 2021). For YEAR
--     use LIKE '%2025'; for MONTH use LIKE '01%'. Never equality for year-only.
--   * fy_flag is the PARTITION KEY (1=FY2017-18 … 11=FY2027-28). Always
--     include `fy_flag = N` in WHERE when the year is known — prunes 90%+ scan.
--   * For COUNT of taxpayers use COUNT(DISTINCT gstin). For COUNT of returns
--     filed use COUNT(*) — one row per return already.
--   * appr_auth uses the ILIKE 'ALL' wildcard convention from DBA reports
--     when officer asks "all authorities" without naming one (e.g. STATE/CENTER).
--
-- FORM-SECTION INDEX (official GSTR-3B form → flat-table column block):
--   3.1(a)   Outward taxable supplies (standard rate)        → osup_det_*
--   3.1(b)   Outward taxable supplies (zero-rated / export)  → osup_zero_*
--   3.1(c)   Other outward supplies (nil-rated, exempt)      → osup_nil_exmp_*
--   3.1(d)   Inward supplies liable to reverse charge        → isup_rev_*
--   3.1(e)   Non-GST outward supplies                         → osup_nongst_*
--   3.1.1(i) Supplies on which ECO pays tax (Sec 9(5))        → eco_sup_*
--   3.1.1(ii)Registered-person supplies through ECO           → eco_reg_sup_*
--   4(A)(1)  ITC Available — Import of goods                  → itc_avl_impg_*
--   4(A)(2)  ITC Available — Import of services               → itc_avl_imps_*
--   4(A)(3)  ITC Available — Inward reverse charge (other)    → itc_avl_isrc_*
--   4(A)(4)  ITC Available — From ISD                         → itc_avl_isd_*
--   4(A)(5)  ITC Available — All other ITC                    → itc_avl_oth_*
--   4(B)(1)  ITC Reversed — Rules 38/42/43 + Sec 17(5)        → itc_rev_rul_*
--   4(B)(2)  ITC Reversed — Others                            → itc_rev_oth_*
--   4(C)     Net ITC Available = (A) − (B)                    → itc_net_*
--   4(D)(1)  ITC reclaimed (reversed under 4(B)(2) earlier)   → itc_inelg_rul_*   ◄── column-name LEGACY: pre-2022-07-05 the form's 4(D)(1) was "Sec 17(5)" (Sec 17(5) moved to 4(B)(1) on 2022-07-05 per Notif. 14/2022). For ret_period < '072022' these columns hold OLD-form (Sec 17(5)) semantics.
--   4(D)(2)  Ineligible ITC — Sec 16(4) + PoS rules           → itc_inelg_oth_*   ◄── pre-2022 was generic "Others"; current = Sec 16(4) + PoS restriction.
--   5(1-3)   Exempt/nil/non-GST inward supplies               → gst_inter, gst_intra, non_gst_inter, non_gst_intra
--   6.1      Payment of tax (overall — cash + ITC set-offs)   → *_cashsetoff, *_intrpd, *_lfeepd, itcsetoff_*_using_*
--   6.1(A)   Payment of tax for non-RCM liability             → *_cashsetoff_wo_rcm, *_intrpd_wo_rcm, *_lfeepd_wo_rcm  (+ itcsetoff_*)
--   6.1(B)   Payment of tax for RCM liability                 → *_cashsetoff_rcm,    *_intrpd_rcm,    *_lfeepd_rcm
--   --       Total tax payable (rollup of 3.1 outward+RCM)    → samt, camt, iamt, csamt (row-root). NOT a form section; this is the "Tax payable" column shown in 6.1. The comprehensive summary report (JRXML) groups them under a column-band labeled "Breakup of tax liability declared (for interest computation)" — that's a REPORT-LAYOUT label, not an official GSTR-3B section.
--   KPI      State Income (Net SGST income to the state)      → state_income (pre-stored)
-- ============================================================
-- DROP TABLE IF EXISTS live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned;
CREATE TABLE IF NOT EXISTS live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned
(
    -- --- Geo + taxpayer-master block (pre-joined; replaces normalized cross-schema joins) ---
    division character varying(150) COLLATE pg_catalog."default", -- Top-level officer jurisdiction. Sample: "Division 1 (ABD)" (Ahmedabad), "Division ** (***)" (anonymized). Indexed.
    range character varying(150) COLLATE pg_catalog."default", -- Mid-level officer jurisdiction (under division). Sample: "Range 1 (ABD)". Indexed. NOT to be confused with the SQL keyword RANGE — quote if needed.
    unit character varying(150) COLLATE pg_catalog."default", -- Lowest-level officer jurisdiction (under range; aka "Ghatak"). Sample: "Ghatak 1 (ABD)". Indexed. NOT to be confused with measurement unit.
    gstin character varying(30) COLLATE pg_catalog."default", -- 15-char Taxpayer GSTIN. Sample: "24AAAAR0599A9AA" (Gujarat textile firm). First 2 chars = state code. For counting taxpayers use COUNT(DISTINCT gstin). Indexed.
    trdnm character varying COLLATE pg_catalog."default", -- Trade name / Firm Name. Sample: "SANGH LIMITED". Free-text varchar — use ILIKE for partial matches.
    lgnmbzpan character varying COLLATE pg_catalog."default", -- Legal Name (per PAN). Sample: "SANGH LIMITED RAJKOT". Often differs from trdnm in branch/city suffix.
    status text COLLATE pg_catalog."default", -- Registration status. Sample: "Active", "Cancelled", "Suspended". For active-taxpayer queries use status = 'Active'.
    rgfmdt date, -- Registration Start Date (the date GSTIN was issued). Sample: "2017-07-01" (GST go-live date for early registrants).
    rgtodt date, -- Registration END Date (NULL for currently-active registrations; populated only when status = 'Cancelled'). Sample: NULL.
    appr_auth character varying(20) COLLATE pg_catalog."default", -- Approving Authority / taxpayer type code. ENUM: "CENTER" (Central jurisdiction), "STATE" (State jurisdiction). When officer asks "all authorities", use ILIKE 'ALL' wildcard (preserves DBA report convention). Indexed.

    -- --- Filing date / return period / calendar block ---
    fil_dt date, -- Filing Date (when the taxpayer filed this return). Sample: "2021-05-14". Native DATE — do NOT cast with TO_DATE(). Indexed.
    ret_period character varying(10) COLLATE pg_catalog."default", -- Return Period in MMYYYY format. Sample: "042021" (=April 2021), "122024" (=Dec 2024). The last 4 chars are the CALENDAR year (Jan–Dec), NOT the financial year — for calendar-year filters use LIKE '%2025'; for month use LIKE '01%'; NEVER use equality for year-only. For FINANCIAL-year (Apr–Mar) scoping use fy_flag — do NOT derive the FY from this column. To DISPLAY the month name / quarter, LEFT JOIN common.mst_3bd_months_t ON ret_period_fl = ret_period and project month_desc / quarter. Indexed.
    mnth_id integer, -- Cumulative month counter (used for chronological grouping across FYs). Sample: 46 (=Apr 2021), 49 (=Jul 2021), 57 (=Mar 2022). Increments monthly from system epoch. Use for ORDER BY when officer wants chronological multi-year timelines.
    fy_flag integer, -- FINANCIAL-Year flag (Apr–Mar) and PARTITION KEY. 1=FY2017-18, 2=FY2018-19, 3=FY2019-20, 4=FY2020-21, 5=FY2021-22, 6=FY2022-23, 7=FY2023-24, 8=FY2024-25, 9=FY2025-26, 10=FY2026-27, 11=FY2027-28. ALWAYS include `fy_flag = N` in WHERE when officer names a financial year — prunes scan to one partition. Use fy_flag in WHERE / GROUP BY / ORDER BY, but NEVER project the raw integer in SELECT — to DISPLAY the financial year, LEFT JOIN common.mst_fy_years_t ON flag_fy = fy_flag and project desc_year (AS financial_year, e.g. '2024-25'). Indexed.
    return_from_date date, -- Start DATE of the return period (the period this return covers, not when filed). Sample: "2021-04-01".
    return_to_date date, -- End DATE of the return period. Sample: "2021-04-30". For "return covers Apr 2021" use return_from_date and return_to_date; for "filed during Apr 2021" use fil_dt.

    -- --- Section 3.1(a) Outward taxable supplies (standard rate) — REGULAR SALES ---
    -- These are normal taxable sales (excluding zero-rated, nil-rated, exempt).
    -- Convention for tax-component columns ACROSS THIS MODULE:
    --   *_samt = SGST (State GST, intra-state)   *_camt = CGST (Central GST, intra-state)
    --   *_iamt = IGST (Inter-state)               *_csamt = Cess
    -- For intra-state sales, SGST == CGST (split of one rate). For inter-state, IGST is single.
    osup_det_txval numeric, -- Total Taxable VAlue of outward taxable supplies (regular sales). Sample: 22106648.64 (SANGH Apr 2021 — ~₹2.2 Cr textile turnover). Form 3.1(a). NOT to be confused with osup_zero/osup_nil_exmp/osup_nongst.
    osup_det_samt numeric, -- SGST on regular outward supplies (intra-state sales). Sample: 768207.68 (SANGH Apr 2021).
    osup_det_camt numeric, -- CGST on regular outward supplies (intra-state sales — equal to SGST). Sample: 768207.68.
    osup_det_iamt numeric, -- IGST on regular outward supplies (INTER-state sales). Sample: 0.00 (no inter-state for SANGH). > 0 indicates inter-state activity.
    osup_det_csamt numeric, -- Cess on regular outward supplies. Sample: 0.00 (no cessable products for SANGH). > 0 only for tobacco/cars/luxury goods.

    -- --- Section 3.1(b) Outward taxable supplies (zero-rated) — EXPORTS + SEZ ---
    osup_zero_txval numeric, -- Total Taxable Value of zero-rated supplies (exports out of India, supplies to SEZ). Sample: 0.00 (domestic-only firm). Form 3.1(b). Zero-rated ≠ nil-rated: exports get ITC benefit even at 0% output.
    osup_zero_samt numeric, -- SGST on zero-rated supplies (usually 0 — supplies are zero-rated). Sample: 0.00.
    osup_zero_camt numeric, -- CGST on zero-rated supplies. Sample: 0.00.
    osup_zero_iamt numeric, -- IGST paid on zero-rated supplies (exports under "with payment" route). Sample: 0.00.
    osup_zero_csamt numeric, -- Cess on zero-rated supplies. Sample: 0.00.

    -- --- Section 3.1(c) Other outward supplies (nil-rated, exempt) ---
    osup_nil_exmp_txval numeric, -- Total Taxable Value of nil-rated and exempt outward supplies (e.g. basic food, education). Sample: 274614.00 (SANGH has some exempt line items). Form 3.1(c). Tax is 0 — no GST applies.
    osup_nil_exmp_samt numeric, -- SGST on nil-rated/exempt supplies (always 0 — exempt = no tax). Sample: 0.00.
    osup_nil_exmp_camt numeric, -- CGST on nil-rated/exempt supplies. Sample: 0.00.
    osup_nil_exmp_iamt numeric, -- IGST on nil-rated/exempt supplies. Sample: 0.00.
    osup_nil_exmp_csamt numeric, -- Cess on nil-rated/exempt supplies. Sample: 0.00.

    -- --- Section 3.1(d) Inward supplies liable to REVERSE CHARGE ---
    -- The TAXPAYER (buyer) pays GST on these inward supplies, not the seller.
    isup_rev_txval numeric, -- Total Taxable Value of inward supplies under reverse charge. Sample: 62400.00 (SANGH receives RCM-liable services monthly — e.g. transporter/legal/security services from unregistered suppliers). Form 3.1(d).
    isup_rev_samt numeric, -- SGST on RCM inward supplies (buyer-paid). Sample: 5616.00 (= 62400 × 9% — intra-state RCM at 18% total split as 9% SGST + 9% CGST).
    isup_rev_camt numeric, -- CGST on RCM inward supplies (buyer-paid). Sample: 5616.00.
    isup_rev_iamt numeric, -- IGST on RCM inward supplies (inter-state RCM). Sample: 0.00.
    isup_rev_csamt numeric, -- Cess on RCM inward supplies. Sample: 0.00.

    -- --- Section 3.1(e) Non-GST outward supplies — OUTSIDE GST SCOPE ---
    osup_nongst_txval numeric, -- Total Taxable Value of non-GST outward supplies (petrol, diesel, alcohol — items outside GST regime). Sample: 0.00 for SANGH (textile firm; doesn't deal in non-GST goods). Form 3.1(e). Tax is intrinsically 0.
    osup_nongst_samt numeric, -- SGST on non-GST supplies (always 0). Sample: 0.00.
    osup_nongst_camt numeric, -- CGST on non-GST supplies. Sample: 0.00.
    osup_nongst_iamt numeric, -- IGST on non-GST supplies. Sample: 0.00.
    osup_nongst_csamt numeric, -- Cess on non-GST supplies. Sample: 0.00.

    -- --- Section 4(A)(1) ITC Available — IMPORT OF GOODS ---
    -- ITC the taxpayer is eligible to claim. NOT to be confused with itc_rev_* (reversed) or itc_inelg_* (blocked) or itc_net_* (net after reversal).
    itc_avl_impg_samt numeric, -- SGST credit available on imported goods (usually 0 — IGST is the relevant component for imports). Sample: 0.00.
    itc_avl_impg_iamt numeric, -- IGST credit available on imported goods (customs IGST paid at port). Sample: 0.00 (SANGH no imports). > 0 for importers.
    itc_avl_impg_camt numeric, -- CGST credit available on imported goods. Sample: 0.00.
    itc_avl_impg_csamt numeric, -- Cess credit available on imported goods. Sample: 0.00.

    -- --- Section 4(A)(2) ITC Available — IMPORT OF SERVICES ---
    itc_avl_imps_samt numeric, -- SGST credit available on imported services. Sample: 0.00.
    itc_avl_imps_iamt numeric, -- IGST credit available on imported services (RCM on foreign service providers). Sample: 0.00.
    itc_avl_imps_camt numeric, -- CGST credit available on imported services. Sample: 0.00.
    itc_avl_imps_csamt numeric, -- Cess credit available on imported services. Sample: 0.00.

    -- --- Section 4(A)(3) ITC Available — INWARD SUPPLIES LIABLE TO REVERSE CHARGE (other) ---
    -- Mirror of isup_rev_* — taxpayer paid RCM tax above, and claims it back as ITC here.
    itc_avl_isrc_samt numeric, -- SGST credit available on RCM inward supplies. Sample: 5616.00 (matches isup_rev_samt — claimed back as ITC).
    itc_avl_isrc_iamt numeric, -- IGST credit available on RCM inward supplies. Sample: 0.00.
    itc_avl_isrc_camt numeric, -- CGST credit available on RCM inward supplies. Sample: 5616.00.
    itc_avl_isrc_csamt numeric, -- Cess credit available on RCM inward supplies. Sample: 0.00.

    -- --- Section 4(A)(4) ITC Available — FROM ISD (Input Service Distributor) ---
    itc_avl_isd_samt numeric, -- SGST credit available from ISD. Sample: 0.00.
    itc_avl_isd_iamt numeric, -- IGST credit available from ISD. Sample: 0.00.
    itc_avl_isd_camt numeric, -- CGST credit available from ISD. Sample: 0.00.
    itc_avl_isd_csamt numeric, -- Cess credit available from ISD. Sample: 0.00.

    -- --- Section 4(A)(5) ITC Available — ALL OTHER ITC (the bulk for most taxpayers) ---
    -- Regular ITC on domestic purchases. For most active taxpayers, MOST of itc_avl is here.
    itc_avl_oth_samt numeric, -- SGST credit available — all other inward supplies (regular purchases). Sample: 483226.00 (SANGH typical monthly intra-state purchase ITC).
    itc_avl_oth_iamt numeric, -- IGST credit available — all other (inter-state purchases). Sample: 4590.00 (small inter-state purchase by SANGH).
    itc_avl_oth_camt numeric, -- CGST credit available — all other. Sample: 483226.00.
    itc_avl_oth_csamt numeric, -- Cess credit available — all other. Sample: 0.00.

    -- --- Section 4(B)(1) ITC Reversed — per Rules 38/42/43 + Section 17(5) ---
    -- ITC the taxpayer had to give back (e.g. for use in exempt outputs, or blocked-credit items).
    itc_rev_rul_samt numeric, -- SGST ITC reversed (rule-based). Sample: 0.00 (SANGH no reversals).
    itc_rev_rul_iamt numeric, -- IGST ITC reversed (rule-based). Sample: 0.00.
    itc_rev_rul_camt numeric, -- CGST ITC reversed (rule-based). Sample: 0.00.
    itc_rev_rul_csamt numeric, -- Cess ITC reversed (rule-based). Sample: 0.00.

    -- --- Section 4(B)(2) ITC Reversed — Others ---
    itc_rev_oth_samt numeric, -- SGST ITC reversed (other reasons). Sample: 0.00.
    itc_rev_oth_iamt numeric, -- IGST ITC reversed (other reasons). Sample: 0.00.
    itc_rev_oth_camt numeric, -- CGST ITC reversed (other reasons). Sample: 0.00.
    itc_rev_oth_csamt numeric, -- Cess ITC reversed (other reasons). Sample: 0.00.

    -- --- Section 4(C) NET ITC Available = (A) − (B) — pre-computed during MV refresh ---
    -- Use itc_net_* directly when officer asks "net ITC available". Do NOT re-derive from itc_avl_* − itc_rev_*.
    itc_net_samt numeric, -- Net SGST ITC available (= itc_avl_isrc_samt + itc_avl_isd_samt + itc_avl_oth_samt + ... − itc_rev_*_samt). Sample: 488842.00 (≈ SANGH's isrc 5616 + oth 483226).
    itc_net_camt numeric, -- Net CGST ITC available. Sample: 488842.00.
    itc_net_iamt numeric, -- Net IGST ITC available. Sample: 4590.00.
    itc_net_csamt numeric, -- Net Cess ITC available. Sample: 0.00.

    -- --- Section 4(D)(1) ITC reclaimed which was reversed under 4(B)(2) in earlier tax period ---
    -- Form-section was amended 2022-07-05 (Notification 14/2022-Central Tax):
    --   PRE-2022-07-05: 4(D)(1) = "ITC ineligible under Section 17(5)" — what the column name "_rul" suggests.
    --   POST-2022-07-05: 4(D)(1) = "ITC reclaimed which was reversed under Table 4(B)(2) in earlier tax period" (Sec 17(5) MOVED to 4(B)(1) → itc_rev_rul_*).
    -- The column name `itc_inelg_rul_*` is legacy from the pre-2022 form; for returns
    -- filed AFTER 2022-07-05 (ret_period >= '072022') these columns hold reclaim values,
    -- NOT blocked-credit values. Officers querying historical periods must keep this
    -- bifurcation in mind. Current data values are reclaim per the report function +
    -- xls labels (which use the post-amendment "4(D)(1)" wording).
    itc_inelg_rul_camt numeric, -- CGST ITC reclaim (Form 4(D)(1), post-2022-07; pre-2022 = Sec 17(5) ineligible). Sample: 0.00.
    itc_inelg_rul_csamt numeric, -- Cess ITC reclaim (Form 4(D)(1), post-2022-07; pre-2022 = Sec 17(5) ineligible). Sample: 0.00.
    itc_inelg_rul_samt numeric, -- SGST ITC reclaim (Form 4(D)(1), post-2022-07; pre-2022 = Sec 17(5) ineligible). Sample: 0.00.
    itc_inelg_rul_iamt numeric, -- IGST ITC reclaim (Form 4(D)(1), post-2022-07; pre-2022 = Sec 17(5) ineligible). Sample: 0.00.

    -- --- Section 4(D)(2) Ineligible ITC under Sec 16(4) + ITC restricted due to PoS rules ---
    -- Form 4(D)(2) post-2022-07 = Sec 16(4) time-bar + PoS-restricted ITC (pre-2022 was simply "Others").
    itc_inelg_oth_camt numeric, -- CGST ineligible ITC under Sec 16(4) / PoS restriction (Form 4(D)(2)). Sample: 0.00.
    itc_inelg_oth_csamt numeric, -- Cess ineligible ITC under Sec 16(4) / PoS restriction (Form 4(D)(2)). Sample: 0.00.
    itc_inelg_oth_samt numeric, -- SGST ineligible ITC under Sec 16(4) / PoS restriction (Form 4(D)(2)). Sample: 0.00.
    itc_inelg_oth_iamt numeric, -- IGST ineligible ITC under Sec 16(4) / PoS restriction (Form 4(D)(2)). Sample: 0.00.

    -- --- Section 5(1)-(3) Exempt / nil-rated / non-GST INWARD supplies (from composition + exempt suppliers) ---
    gst_inter numeric, -- Value of INTER-State inward supplies from composition-scheme/exempt/nil-rated suppliers (GST applicable but exempt at supplier end). Sample: 0.00. Form 5(1) Inter-State.
    gst_intra numeric, -- Value of INTRA-State inward supplies from composition-scheme/exempt/nil-rated suppliers. Sample: 0.00. Form 5(1) Intra-State.
    non_gst_inter numeric, -- Value of INTER-State NON-GST inward supplies (purchases of petrol/alcohol etc. from other states). Sample: 0.00. Form 5(2) Inter-State.
    non_gst_intra numeric, -- Value of INTRA-State NON-GST inward supplies. Sample: 0.00. Form 5(3) Intra-State.

    -- --- Section 6.1 / 6.1(A) Payment of tax — ITC SET-OFFS (how liability was cleared using credit) ---
    -- "itcsetoff_X_using_Y" = X-liability cleared using Y-credit. e.g. itcsetoff_sgst_using_igst = SGST liability cleared with IGST credit.
    -- Cross-credit utilization rules: IGST credit can clear IGST→CGST→SGST (any). SGST credit clears SGST/IGST only (not CGST). CGST credit clears CGST/IGST only (not SGST). CESS credit clears Cess only.
    itcsetoff_sgst_using_sgst numeric, -- SGST liability cleared using SGST credit (primary path). Sample: 488842.00.
    itcsetoff_sgst_using_igst numeric, -- SGST liability cleared using IGST credit (when SGST credit insufficient; ADDS to state_income). Sample: 0.00.
    sgst_cashsetoff numeric, -- SGST liability paid in cash (when ITC insufficient). Sample: 284982.00.
    s_intrpd numeric, -- SGST interest paid in cash (for delayed filing). Sample: 0.00 (SANGH timely filer).
    s_lfeepd numeric, -- SGST late fee paid in cash. Sample: 0.00.
    itcsetoff_cgst_using_cgst numeric, -- CGST liability cleared using CGST credit. Sample: 488842.00.
    itcsetoff_cgst_using_igst numeric, -- CGST liability cleared using IGST credit. Sample: 4590.00 (SANGH used the small inter-state ITC to clear CGST).
    cgst_cashsetoff numeric, -- CGST liability paid in cash. Sample: 280392.00 (= sgst_cashsetoff − itcsetoff_cgst_using_igst).
    c_intrpd numeric, -- CGST interest paid in cash. Sample: 0.00.
    c_lfeepd numeric, -- CGST late fee paid in cash. Sample: 0.00.
    itcsetoff_igst_using_sgst numeric, -- IGST liability cleared using SGST credit (SUBTRACTS from state_income — SGST outflow). Sample: 0.00.
    itcsetoff_igst_using_cgst numeric, -- IGST liability cleared using CGST credit. Sample: 0.00.
    itcsetoff_igst_using_igst numeric, -- IGST liability cleared using IGST credit (primary path for inter-state). Sample: 0.00.
    igst_cashsetoff numeric, -- IGST liability paid in cash. Sample: 0.00.
    i_intrpd numeric, -- IGST interest paid in cash. Sample: 0.00.
    i_lfeepd numeric, -- IGST late fee paid in cash. Sample: 0.00.
    itcsetoff_cess_using_cess numeric, -- Cess liability cleared using Cess credit (only cross-utilization allowed for cess). Sample: 0.00.
    cs_intrpd numeric, -- Cess interest paid in cash. Sample: 0.00.
    cs_lfeepd numeric, -- Cess late fee paid in cash. Sample: 0.00.
    cess_cashsetoff numeric, -- Cess liability paid in cash. Sample: 0.00.

    -- --- Total tax payable for the period (row-level rollup; NOT a separate form section) ---
    -- These are the consolidated SGST/CGST/IGST/CESS liability totals computed from Section 3.1 outward supplies
    -- + 3.1(d) inward RCM amounts. They are the values that appear in the official Form GSTR-3B Section 6.1 as the
    -- "Tax payable" column (column 2 of the 6.1 table). NOT to be confused with osup_det_samt etc. (those are the
    -- per-section breakdowns these aggregate). The comprehensive summary report (JRXML) groups these under a
    -- column-band labeled "Breakup of tax liability declared (for interest computation)" — that's a
    -- REPORT-LAYOUT label, NOT an official GSTR-3B section. (The form has no Section 7.)
    samt numeric, -- TOTAL SGST tax payable this period (rollup of 3.1 outward+RCM SGST amounts). Sample: 773823.68 (≈ osup_det_samt 768207.68 + isup_rev_samt 5616 for SANGH). Shown as "Tax payable" in Form 6.1.
    camt numeric, -- TOTAL CGST tax payable this period (rollup of 3.1 outward+RCM CGST amounts). Sample: 773823.68. Shown as "Tax payable" in Form 6.1.
    iamt numeric, -- TOTAL IGST tax payable this period (rollup of 3.1 outward+RCM IGST amounts). Sample: 0.00. Shown as "Tax payable" in Form 6.1.
    csamt numeric, -- TOTAL Cess payable this period (rollup of 3.1 outward+RCM Cess amounts). Sample: 0.00. Shown as "Tax payable" in Form 6.1.

    -- --- State Income KPI (pre-computed; the headline officer metric) ---
    -- Formula (DBA-confirmed 2026-05-28; matches xls header verbatim):
    --   state_income = (sgst_cashsetoff + s_intrpd + s_lfeepd)   -- SGST paid via cash + interest + late fee (state's direct receipt)
    --                + itcsetoff_sgst_using_igst                 -- SGST liability cleared using IGST credit (income to state)
    --                − itcsetoff_igst_using_sgst                 -- IGST liability cleared using SGST credit (outflow from state)
    -- Use this column DIRECTLY when officer asks "state income" / "SGST revenue" / "net SGST to state".
    -- Do NOT re-derive in SQL — the formula's components are already rounded at MV refresh time.
    state_income numeric, -- Net SGST Income to the state for this return (pre-computed; SGST cash + interest + late fee + SGST-via-IGST credit − IGST-via-SGST credit). Sample: 284982.00 (SANGH Apr 2021 — the state's net take from this filer this month). Use directly; do NOT re-derive.

    -- --- Section 6.1(B) Payment of tax for RCM LIABILITY (Reverse Charge — buyer-paid tax) ---
    -- Mirror of *_cashsetoff/intrpd/lfeepd but ONLY for the RCM portion of liability.
    -- NOT to be confused with *_wo_rcm (non-RCM payments) — these two splits together SUM to the row-root *_cashsetoff/intrpd/lfeepd.
    igst_cashsetoff_rcm numeric, -- IGST paid in cash for RCM liability. Sample: 0.00 (SANGH's RCM is intra-state, so no IGST).
    cgst_cashsetoff_rcm numeric, -- CGST paid in cash for RCM liability. Sample: 5616.00 (matches the buyer-paid CGST on RCM inward supplies).
    sgst_cashsetoff_rcm numeric, -- SGST paid in cash for RCM liability. Sample: 5616.00.
    cess_cashsetoff_rcm numeric, -- Cess paid in cash for RCM liability. Sample: 0.00.
    i_intrpd_rcm numeric, -- IGST interest paid in cash for RCM. Sample: 0.00.
    c_intrpd_rcm numeric, -- CGST interest paid in cash for RCM. Sample: 0.00.
    s_intrpd_rcm numeric, -- SGST interest paid in cash for RCM. Sample: 0.00.
    cs_intrpd_rcm numeric, -- Cess interest paid in cash for RCM. Sample: 0.00.
    s_lfeepd_rcm numeric, -- SGST late fee paid in cash for RCM. Sample: 0.00.
    c_lfeepd_rcm numeric, -- CGST late fee paid in cash for RCM. Sample: 0.00.
    i_lfeepd_rcm numeric, -- IGST late fee paid in cash for RCM. Sample: 0.00.
    cs_lfeepd_rcm numeric, -- Cess late fee paid in cash for RCM. Sample: 0.00.

    -- --- Section 6.1(A) Payment of tax for NON-RCM LIABILITY (regular seller-paid tax) ---
    -- Mirror of *_rcm but for non-RCM portion. (row-root cashsetoff) = (rcm cashsetoff) + (wo_rcm cashsetoff).
    igst_cashsetoff_wo_rcm numeric, -- IGST paid in cash for non-RCM liability. Sample: 0.00.
    cgst_cashsetoff_wo_rcm numeric, -- CGST paid in cash for non-RCM liability. Sample: 274776.00 (= cgst_cashsetoff 280392 − cgst_cashsetoff_rcm 5616).
    sgst_cashsetoff_wo_rcm numeric, -- SGST paid in cash for non-RCM liability. Sample: 279366.00 (= sgst_cashsetoff 284982 − sgst_cashsetoff_rcm 5616).
    cess_cashsetoff_wo_rcm numeric, -- Cess paid in cash for non-RCM liability. Sample: 0.00.
    i_intrpd_wo_rcm numeric, -- IGST interest paid in cash for non-RCM. Sample: 0.00.
    c_intrpd_wo_rcm numeric, -- CGST interest paid in cash for non-RCM. Sample: 0.00.
    s_intrpd_wo_rcm numeric, -- SGST interest paid in cash for non-RCM. Sample: 0.00.
    cs_intrpd_wo_rcm numeric, -- Cess interest paid in cash for non-RCM. Sample: 0.00.
    s_lfeepd_wo_rcm numeric, -- SGST late fee paid in cash for non-RCM. Sample: 0.00.
    c_lfeepd_wo_rcm numeric, -- CGST late fee paid in cash for non-RCM. Sample: 0.00.
    i_lfeepd_wo_rcm numeric, -- IGST late fee paid in cash for non-RCM. Sample: 0.00.
    cs_lfeepd_wo_rcm numeric, -- Cess late fee paid in cash for non-RCM. Sample: 0.00.

    -- --- Section 3.1.1(i) Supplies on which E-COMMERCE OPERATOR pays tax (Sec 9(5)) ---
    -- For taxpayers selling on marketplaces (Amazon, Flipkart, etc.), ECO is liable for tax on specified services (cab, restaurant, housekeeping).
    eco_sup_txval numeric, -- Total Taxable Value of supplies on which ECO pays tax. Sample: 0.00 (SANGH not a marketplace seller). > 0 for restaurants on Swiggy/Zomato, cab operators on Ola/Uber, etc.
    eco_sup_sgst numeric, -- SGST on ECO-tax supplies (paid by ECO, not by taxpayer). Sample: 0.00.
    eco_sup_cgst numeric, -- CGST on ECO-tax supplies. Sample: 0.00.
    eco_sup_igst numeric, -- IGST on ECO-tax supplies. Sample: 0.00.
    eco_sup_cess numeric, -- Cess on ECO-tax supplies. Sample: 0.00.

    -- --- Section 3.1.1(ii) Supplies made by REGISTERED PERSON THROUGH ECO ---
    -- NOT to be confused with eco_sup_* (where ECO pays tax). Here, the taxpayer (registered person) supplies through ECO but pays tax themselves.
    eco_reg_sup_txval numeric, -- Total Taxable Value of supplies the registered taxpayer made through an ECO (tax paid by taxpayer, not by ECO). Sample: 0.00 (SANGH doesn't sell through marketplaces).
    eco_reg_sup_sgst numeric, -- SGST on registered-via-ECO supplies. Sample: 0.00.
    eco_reg_sup_cgst numeric, -- CGST on registered-via-ECO supplies. Sample: 0.00.
    eco_reg_sup_igst numeric, -- IGST on registered-via-ECO supplies. Sample: 0.00.
    eco_reg_sup_cess numeric, -- Cess on registered-via-ECO supplies. Sample: 0.00.

    "current_date" date -- MV refresh stamp: the date this row was last refreshed by the DBA pipeline. Sample: "2026-04-20". NOT the return-period date — for that use ret_period/return_from_date.
) PARTITION BY LIST (fy_flag);

-- ============================================================
-- QUERY-TIME DERIVED KPIs — NOT stored. Compute in SELECT when officer asks.
-- These mirror the report functions in r3b_cmprhensve_summary_1_upd.sql /
-- r3b_cmprhensve_month_wise_detailed.sql, so the SQL the agent emits matches
-- what officers see in PDF/Excel reports.
-- ============================================================
-- sgst_cashsetoff_final        = sgst_cashsetoff + s_intrpd + s_lfeepd                -- SGST cash outflow incl. interest + late fee
-- cgst_cashsetoff_final        = cgst_cashsetoff + c_intrpd + c_lfeepd                -- CGST cash outflow incl. interest + late fee
-- igst_cashsetoff_final        = igst_cashsetoff + i_intrpd + i_lfeepd                -- IGST cash outflow incl. interest + late fee
-- cess_cashsetoff_final        = cess_cashsetoff + cs_intrpd + cs_lfeepd              -- Cess cash outflow incl. interest + late fee
-- itcsetoff_sgst_using_igst_final = itcsetoff_sgst_using_igst                         -- (passthrough; reserved for future netting)
-- itcsetoff_igst_using_sgst_final = itcsetoff_igst_using_sgst                         -- (passthrough)
-- total_itc_available_*amt     = itc_avl_impg_*amt + itc_avl_imps_*amt + itc_avl_isrc_*amt + itc_avl_isd_*amt + itc_avl_oth_*amt
-- total_itc_reversed_*amt      = itc_rev_rul_*amt  + itc_rev_oth_*amt
-- total_itc_ineligible_*amt    = itc_inelg_rul_*amt + itc_inelg_oth_*amt
-- ============================================================

-- ============================================================
-- JOINS — decode/master lookups ONLY.
-- This is a SINGLE denormalized fact table: all gstin, ret_period, geo,
-- taxpayer-master, supply, ITC, payment, RCM, and ECO fields are on the SAME
-- ROW. Do NOT JOIN it back to any tbl_gst_rtn_r3b* base table (those are the
-- pre-denormalization source). The ONLY joins permitted are small, 1:1
-- LEFT JOINs to the shared common.* master tables below, used purely to DECODE
-- coded columns into officer-readable labels (fy_flag → "2024-25",
-- ret_period → "March"/"Q4"). These are conformed decode-dimensions, not the
-- eliminated fact-table chain — they never multiply rows.
--
-- Join hints:
-- live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned.fy_flag can be joined with common.mst_fy_years_t.flag_fy
-- live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned.ret_period can be joined with common.mst_3bd_months_t.ret_period_fl
-- ============================================================
