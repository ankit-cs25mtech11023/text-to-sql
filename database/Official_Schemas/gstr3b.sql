-- ============================================================
-- Schema: public
-- Module: GSTR3B (Monthly Summary Return for GST)
-- Description: Contains GST return filing data for Indian taxpayers.
--
-- Tables (brief):
-- 1) public.tbl_gst_rtn_r3b                       -- MAIN TABLE - has gstin and ret_period
-- 2) public.tbl_gst_rtn_r3b_inward_sup            -- Parent for inward supplies details
-- 3) public.tbl_gst_rtn_r3b_inward_sup_isup_details -- Inward supplies (exempt/nil/non-GST) details
-- 4) public.tbl_gst_rtn_r3b_itc_elg               -- Parent for ITC (Input Tax Credit) details
-- 5) public.tbl_gst_rtn_r3b_itc_elg_itc_avl       -- ITC Available amounts
-- 6) public.tbl_gst_rtn_r3b_itc_elg_itc_inelg     -- ITC Ineligible amounts
-- 7) public.tbl_gst_rtn_r3b_itc_elg_itc_net       -- Net ITC Available amounts
-- 8) public.tbl_gst_rtn_r3b_itc_elg_itc_rev       -- ITC Reversed amounts
-- 9) public.tbl_gst_rtn_r3b_sup_details           -- Parent for supply details
-- 10) public.tbl_gst_rtn_r3b_sup_details_isuprev  -- Inward supplies under reverse charge
-- 11) public.tbl_gst_rtn_r3b_sup_details_osupdet  -- Outward taxable supplies
-- 12) public.tbl_gst_rtn_r3b_sup_details_osupnilexmp -- Outward nil-rated/exempt supplies
-- 13) public.tbl_gst_rtn_r3b_sup_details_osupnongst -- Non-GST outward supplies
-- 14) public.tbl_gst_rtn_r3b_sup_details_osupzero -- Zero-rated outward supplies
-- 15) public.tbl_gst_rtn_r3b_tx_pmt               -- Parent for tax payment details
-- 16) public.tbl_gst_rtn_r3b_tx_pmt_pd_cash       -- Tax paid via cash ledger
-- 17) public.tbl_gst_rtn_r3b_tx_pmt_pd_itc        -- Tax paid via ITC (Input Tax Credit)
-- ============================================================

-- MAIN TABLE for GSTR3B returns. JOIN THIS TABLE FOR ALL QUERIES needing taxpayer or period information. This is the ONLY table with gstin and ret_period.
CREATE TABLE public.tbl_gst_rtn_r3b (
  idtbl_gst_rtn_r3b BIGINT PRIMARY KEY, -- Primary key (internal ID, ~24M+ values).
  gstin VARCHAR, -- 15-char Taxpayer GSTIN. Sample: "03DLMPS0000E1Z1", "03AAACP0000K1ZF". First 2 chars = state code. For counting taxpayers use COUNT(DISTINCT gstin). This column ONLY exists in this main table.
  ret_period VARCHAR, -- Return Period in MMYYYY format. Sample: "012026" (=Jan 2026), "122024" (=Dec 2024). YEAR=last 4 chars, MONTH=first 2. For "year 2025" use ret_period LIKE '%2025'. For "January" use ret_period LIKE '01%'. NEVER use equality for year-only filters.
  fil_dt VARCHAR, -- Filing Date in DD-MM-YYYY format. Sample: "18-02-2026". VARCHAR string; use TO_DATE(fil_dt, 'DD-MM-YYYY') for date math.
  process_date VARCHAR, -- Backend processing date in YYYY-MM-DD (ISO) format. Sample: "2026-02-18". Different format from fil_dt — do NOT mix.
  process_no VARCHAR -- Processing batch number. Sample: "38".
);

-- Parent table for inward supplies section. Links main table to inward supply details. Must JOIN through this to get taxpayer info.
CREATE TABLE public.tbl_gst_rtn_r3b_inward_sup (
  idtbl_gst_rtn_r3b_inward_sup BIGINT PRIMARY KEY, -- Primary key
  idtbl_gst_rtn_r3b BIGINT REFERENCES tbl_gst_rtn_r3b(idtbl_gst_rtn_r3b), -- FK to main table. JOIN through this to access gstin and ret_period.
);

-- Inward supplies details (composite/nil-rated/exempt + non-GST purchases). Two rows per return: one with ty='GST' (composite/nil/exempt), one with ty='NONGST'.
CREATE TABLE public.tbl_gst_rtn_r3b_inward_sup_isup_details (
  idtbl_gst_rtn_r3b_inward_sup_isup_details BIGINT PRIMARY KEY, -- Primary key
  ty TEXT, -- Type of inward supply. ENUM — only two values: "GST" (composite-scheme/nil-rated/exempt purchases) and "NONGST" (purchases of items outside GST scope, e.g. petrol, alcohol).
  inter NUMERIC, -- Inter-State supplies value (purchases from other states).
  intra NUMERIC, -- Intra-State supplies value (purchases within same state).
  idtbl_gst_rtn_r3b_inward_sup BIGINT REFERENCES tbl_gst_rtn_r3b_inward_sup(idtbl_gst_rtn_r3b_inward_sup), -- FK to parent. Must JOIN through inward_sup then to main table for gstin.
);

-- Parent table for ITC (Input Tax Credit) section. Links main table to all ITC detail tables (itc_avl, itc_rev, itc_inelg, itc_net).
CREATE TABLE public.tbl_gst_rtn_r3b_itc_elg (
  idtbl_gst_rtn_r3b_itc_elg BIGINT PRIMARY KEY, -- Primary key
  idtbl_gst_rtn_r3b BIGINT REFERENCES tbl_gst_rtn_r3b(idtbl_gst_rtn_r3b), -- FK to main table. JOIN through this to access gstin and ret_period for ITC queries.
);

-- ITC Available amounts - Input Tax Credit that can be claimed by the taxpayer. Multiple rows per return (one per ty).
CREATE TABLE public.tbl_gst_rtn_r3b_itc_elg_itc_avl (
  idtbl_gst_rtn_r3b_itc_elg_itc_avl BIGINT PRIMARY KEY, -- Primary key
  ty TEXT, -- Type of ITC available. ENUM — observed values: "IMPG" (=Import of Goods), "IMPS" (=Import of Services), "ISRC" (=Inward Supplies liable to Reverse Charge), "ISD" (=Input Service Distributor credit), "OTH" (=All Other ITC). Most active taxpayers populate "OTH" only.
  iamt NUMERIC, -- IGST available (inter-state purchases).
  camt NUMERIC, -- CGST available (central portion of intra-state).
  samt NUMERIC, -- SGST available (state portion of intra-state).
  csamt NUMERIC, -- Cess available.
  idtbl_gst_rtn_r3b_itc_elg BIGINT REFERENCES tbl_gst_rtn_r3b_itc_elg(idtbl_gst_rtn_r3b_itc_elg), -- FK to ITC parent. Must JOIN through itc_elg then to main table for gstin.
);

-- ITC Ineligible amounts - Input Tax Credit that CANNOT be claimed (blocked credit). Two rows per return.
CREATE TABLE public.tbl_gst_rtn_r3b_itc_elg_itc_inelg (
  idtbl_gst_rtn_r3b_itc_elg_itc_inelg BIGINT PRIMARY KEY, -- Primary key
  ty TEXT, -- Type of ineligible ITC. ENUM — only two values: "RUL" (=Section 17(5) blocked credit / Rule 42 & 43 reversal) and "OTH" (=Other ineligible). Almost always 0 in data.
  iamt NUMERIC, -- IGST ineligible amount.
  camt NUMERIC, -- CGST ineligible amount.
  samt NUMERIC, -- SGST ineligible amount.
  csamt NUMERIC, -- Cess ineligible amount.
  idtbl_gst_rtn_r3b_itc_elg BIGINT REFERENCES tbl_gst_rtn_r3b_itc_elg(idtbl_gst_rtn_r3b_itc_elg), -- FK to ITC parent. Must JOIN through itc_elg then to main table for gstin.
);

-- Net ITC Available - Final available credit after adjustments (available minus reversed/ineligible). One row per return (no `ty` partitioning).
CREATE TABLE public.tbl_gst_rtn_r3b_itc_elg_itc_net (
  idtbl_gst_rtn_r3b_itc_elg_itc_net BIGINT PRIMARY KEY, -- Primary key
  iamt NUMERIC, -- IGST net available.
  camt NUMERIC, -- CGST net available. Sample: 990.00, 67900.00.
  samt NUMERIC, -- SGST net available.
  csamt NUMERIC, -- Cess net available.
  idtbl_gst_rtn_r3b_itc_elg BIGINT REFERENCES tbl_gst_rtn_r3b_itc_elg(idtbl_gst_rtn_r3b_itc_elg), -- FK to ITC parent. Must JOIN through itc_elg then to main table for gstin.
);

-- ITC Reversed amounts - Input Tax Credit that was reversed (taken back) by the taxpayer. Two rows per return mirroring ineligible.
CREATE TABLE public.tbl_gst_rtn_r3b_itc_elg_itc_rev (
  idtbl_gst_rtn_r3b_itc_elg_itc_rev BIGINT PRIMARY KEY, -- Primary key
  ty TEXT, -- Type/reason for reversal. ENUM — only two values: "RUL" (=Rule 42 & 43 — proportional reversal for exempt/personal use) and "OTH" (=Other reversals). Usually 0 in data.
  iamt NUMERIC, -- IGST reversed amount.
  camt NUMERIC, -- CGST reversed amount.
  samt NUMERIC, -- SGST reversed amount.
  csamt NUMERIC, -- Cess reversed amount.
  idtbl_gst_rtn_r3b_itc_elg BIGINT REFERENCES tbl_gst_rtn_r3b_itc_elg(idtbl_gst_rtn_r3b_itc_elg), -- FK to ITC parent. Must JOIN through itc_elg then to main table for gstin.
);

-- Parent table for supply details section. Links main table to all supply detail tables (osup*, isup*).
CREATE TABLE public.tbl_gst_rtn_r3b_sup_details (
  idtbl_gst_rtn_r3b_sup_details BIGINT PRIMARY KEY, -- Primary key
  idtbl_gst_rtn_r3b BIGINT REFERENCES tbl_gst_rtn_r3b(idtbl_gst_rtn_r3b), -- FK to main table. JOIN through this to access gstin and ret_period for supply queries.
);

-- Inward supplies under reverse charge - purchases where buyer pays tax instead of seller. One row per return.
CREATE TABLE public.tbl_gst_rtn_r3b_sup_details_isuprev (
  idtbl_gst_rtn_r3b_sup_details_isuprev BIGINT PRIMARY KEY, -- Primary key
  txval NUMERIC, -- Total Taxable turnover value of supplies.
  iamt NUMERIC, -- IGST amount.
  camt NUMERIC, -- CGST amount.
  samt NUMERIC, -- SGST amount.
  csamt NUMERIC, -- Cess amount.
  idtbl_gst_rtn_r3b_sup_details BIGINT REFERENCES tbl_gst_rtn_r3b_sup_details(idtbl_gst_rtn_r3b_sup_details), -- FK to supply parent. Must JOIN through sup_details then to main table for gstin.
);

-- Outward taxable supplies/Liability - regular taxable sales (excluding zero-rated, nil-rated, exempt). One row per return.
CREATE TABLE public.tbl_gst_rtn_r3b_sup_details_osupdet (  
  idtbl_gst_rtn_r3b_sup_details_osupdet BIGINT PRIMARY KEY, -- Primary key
  txval NUMERIC, -- Total Taxable turnover value of outward supplies (sales). Sample: 540330.64, 1219448.00, 12108.28 for active taxpayers;
  iamt NUMERIC, -- IGST Liability on inter-state sales. Sample: 91419.00, 1982.27. Use IGST > 0 to detect inter-state activity.
  camt NUMERIC, -- CGST Liability on intra-state sales. Sample: 13508.33, 64042.00.
  samt NUMERIC, -- SGST Liability on intra-state sales.
  csamt NUMERIC, -- Cess Liability on sales.
  idtbl_gst_rtn_r3b_sup_details BIGINT REFERENCES tbl_gst_rtn_r3b_sup_details(idtbl_gst_rtn_r3b_sup_details), -- FK to supply parent. Must JOIN through sup_details then to main table for gstin.
);

-- Outward nil-rated and exempt supplies - sales not subject to GST or at 0% rate. One row per return.
CREATE TABLE public.tbl_gst_rtn_r3b_sup_details_osupnilexmp (  
  idtbl_gst_rtn_r3b_sup_details_osupnilexmp BIGINT PRIMARY KEY, -- Primary key
  txval NUMERIC, -- Total Taxable turnover value of nil-rated/exempt supplies.
  iamt NUMERIC, -- IGST amount
  camt NUMERIC, -- CGST amount
  samt NUMERIC, -- SGST amount
  csamt NUMERIC, -- Cess amount
  idtbl_gst_rtn_r3b_sup_details BIGINT REFERENCES tbl_gst_rtn_r3b_sup_details(idtbl_gst_rtn_r3b_sup_details), -- FK to supply parent. Must JOIN through sup_details then to main table for gstin.
);

-- Non-GST outward supplies - sales of goods/services outside GST scope (petrol, alcohol). One row per return.
CREATE TABLE public.tbl_gst_rtn_r3b_sup_details_osupnongst (
  idtbl_gst_rtn_r3b_sup_details_osupnongst BIGINT PRIMARY KEY, -- Primary key
  txval NUMERIC, -- Total Taxable turnover value of non-GST supplies.
  iamt NUMERIC, -- IGST amount
  camt NUMERIC, -- CGST amount
  samt NUMERIC, -- SGST amount
  csamt NUMERIC, -- Cess amount
  idtbl_gst_rtn_r3b_sup_details BIGINT REFERENCES tbl_gst_rtn_r3b_sup_details(idtbl_gst_rtn_r3b_sup_details), -- FK to supply parent. Must JOIN through sup_details then to main table for gstin.
);

-- Zero-rated outward supplies - exports and supplies to SEZ (taxed at 0% but with ITC benefit). One row per return.
CREATE TABLE public.tbl_gst_rtn_r3b_sup_details_osupzero (
  idtbl_gst_rtn_r3b_sup_details_osupzero BIGINT PRIMARY KEY, -- Primary key
  txval NUMERIC, -- Total Taxable turnover value of zero-rated supplies (exports + SEZ).
  iamt NUMERIC, -- IGST amount on exports paid.
  camt NUMERIC, -- CGST amount.
  samt NUMERIC, -- SGST amount.
  csamt NUMERIC, -- Cess amount.
  idtbl_gst_rtn_r3b_sup_details BIGINT REFERENCES tbl_gst_rtn_r3b_sup_details(idtbl_gst_rtn_r3b_sup_details), -- FK to supply parent. Must JOIN through sup_details then to main table for gstin.
);

-- Parent table for tax payment section. Links main table to payment detail tables (pd_cash, pd_itc). This is a linking table no amounts in this table.
CREATE TABLE public.tbl_gst_rtn_r3b_tx_pmt (
  idtbl_gst_rtn_r3b_tx_pmt BIGINT PRIMARY KEY, -- Primary key
  idtbl_gst_rtn_r3b BIGINT REFERENCES tbl_gst_rtn_r3b(idtbl_gst_rtn_r3b), -- FK to main table. JOIN through this to access gstin and ret_period for payment queries.
);

-- Tax paid through cash ledger - direct tax payments from electronic cash ledger. Multiple rows per return (one per liability line).
CREATE TABLE public.tbl_gst_rtn_r3b_tx_pmt_pd_cash (
  idtbl_gst_rtn_r3b_tx_pmt_pd_cash BIGINT PRIMARY KEY, -- Primary key
  liab_ldg_id TEXT, -- Liability ledger ID (numeric string identifying the obligation being paid). Sample: "975974661", "975974317". Sequential per taxpayer.
  trans_typ TEXT, -- Transaction type code (5-digit numeric string). ENUM — observed values: "30002" (=regular tax payment), "30003" (=interest / late fee / penalty payment).
  ipd NUMERIC, -- IGST paid via cash. Sample: 10529.00, 6066.00.
  cpd NUMERIC, -- CGST paid via cash. Sample: 990.00, 214436.00, 8568.00.
  spd NUMERIC, -- SGST paid via cash.
  cspd NUMERIC, -- Cess paid via cash.
  i_intrpd NUMERIC, -- IGST interest paid.
  c_intrpd NUMERIC, -- CGST interest paid.
  s_intrpd NUMERIC, -- SGST interest paid.
  cs_intrpd NUMERIC, -- Cess interest paid.
  i_lfeepd NUMERIC, -- IGST late fee paid.
  c_lfeepd NUMERIC, -- CGST late fee paid.
  s_lfeepd NUMERIC, -- SGST late fee paid.
  cs_lfeepd NUMERIC, -- Cess late fee paid.
  idtbl_gst_rtn_r3b_tx_pmt BIGINT REFERENCES tbl_gst_rtn_r3b_tx_pmt(idtbl_gst_rtn_r3b_tx_pmt), -- FK to payment parent. Must JOIN through tx_pmt then to main table for gstin.
);

-- Tax paid through ITC (Input Tax Credit) - tax liability offset using available credit. Multiple rows per return (one per liability line). Cross-credit utilization columns: i_pdc means IGST liability paid using CGST credit, etc.
CREATE TABLE public.tbl_gst_rtn_r3b_tx_pmt_pd_itc (
  idtbl_gst_rtn_r3b_tx_pmt_pd_itc BIGINT PRIMARY KEY, -- Primary key
  liab_ldg_id TEXT, -- Liability ledger ID (numeric string). Sample: "975974660", "975974317". Same series as pd_cash.
  trans_typ TEXT, -- Transaction type code. Almost always "30002" here (regular tax payment via ITC; interest/penalties cannot be paid by ITC).
  i_pdi NUMERIC, -- IGST liability paid using IGST credit. Sample: 33952.00, 625.00.
  i_pdc NUMERIC, -- IGST liability paid using CGST credit. Sample: 1357.00, 3858.00.
  i_pds NUMERIC, -- IGST liability paid using SGST credit. Sample: 43080.00.
  c_pdi NUMERIC, -- CGST liability paid using IGST credit. Sample: 13508.00.
  c_pdc NUMERIC, -- CGST liability paid using CGST credit. Sample: 64042.00, 784832.00.
  s_pdi NUMERIC, -- SGST liability paid using IGST credit. Sample: 13508.00.
  s_pds NUMERIC, -- SGST liability paid using SGST credit. Sample: 64042.00, 854210.00.
  cs_pdcs NUMERIC, -- Cess liability paid using Cess credit.
  idtbl_gst_rtn_r3b_tx_pmt BIGINT REFERENCES tbl_gst_rtn_r3b_tx_pmt(idtbl_gst_rtn_r3b_tx_pmt), -- FK to payment parent. Must JOIN through tx_pmt then to main table for gstin.
);

-- ============================================================
-- JOIN HINTS FOR SQL GENERATION
-- These show the join paths from detail tables to main table
-- ============================================================

-- INWARD SUPPLIES joins:
-- tbl_gst_rtn_r3b_inward_sup.idtbl_gst_rtn_r3b can be joined with tbl_gst_rtn_r3b.idtbl_gst_rtn_r3b
-- tbl_gst_rtn_r3b_inward_sup_isup_details.idtbl_gst_rtn_r3b_inward_sup can be joined with tbl_gst_rtn_r3b_inward_sup.idtbl_gst_rtn_r3b_inward_sup

-- ITC (Input Tax Credit) joins:
-- tbl_gst_rtn_r3b_itc_elg.idtbl_gst_rtn_r3b can be joined with tbl_gst_rtn_r3b.idtbl_gst_rtn_r3b
-- tbl_gst_rtn_r3b_itc_elg_itc_avl.idtbl_gst_rtn_r3b_itc_elg can be joined with tbl_gst_rtn_r3b_itc_elg.idtbl_gst_rtn_r3b_itc_elg
-- tbl_gst_rtn_r3b_itc_elg_itc_inelg.idtbl_gst_rtn_r3b_itc_elg can be joined with tbl_gst_rtn_r3b_itc_elg.idtbl_gst_rtn_r3b_itc_elg
-- tbl_gst_rtn_r3b_itc_elg_itc_net.idtbl_gst_rtn_r3b_itc_elg can be joined with tbl_gst_rtn_r3b_itc_elg.idtbl_gst_rtn_r3b_itc_elg
-- tbl_gst_rtn_r3b_itc_elg_itc_rev.idtbl_gst_rtn_r3b_itc_elg can be joined with tbl_gst_rtn_r3b_itc_elg.idtbl_gst_rtn_r3b_itc_elg

-- SUPPLY DETAILS joins:
-- tbl_gst_rtn_r3b_sup_details.idtbl_gst_rtn_r3b can be joined with tbl_gst_rtn_r3b.idtbl_gst_rtn_r3b
-- tbl_gst_rtn_r3b_sup_details_isuprev.idtbl_gst_rtn_r3b_sup_details can be joined with tbl_gst_rtn_r3b_sup_details.idtbl_gst_rtn_r3b_sup_details
-- tbl_gst_rtn_r3b_sup_details_osupdet.idtbl_gst_rtn_r3b_sup_details can be joined with tbl_gst_rtn_r3b_sup_details.idtbl_gst_rtn_r3b_sup_details
-- tbl_gst_rtn_r3b_sup_details_osupnilexmp.idtbl_gst_rtn_r3b_sup_details can be joined with tbl_gst_rtn_r3b_sup_details.idtbl_gst_rtn_r3b_sup_details
-- tbl_gst_rtn_r3b_sup_details_osupnongst.idtbl_gst_rtn_r3b_sup_details can be joined with tbl_gst_rtn_r3b_sup_details.idtbl_gst_rtn_r3b_sup_details
-- tbl_gst_rtn_r3b_sup_details_osupzero.idtbl_gst_rtn_r3b_sup_details can be joined with tbl_gst_rtn_r3b_sup_details.idtbl_gst_rtn_r3b_sup_details

-- TAX PAYMENT joins:
-- tbl_gst_rtn_r3b_tx_pmt.idtbl_gst_rtn_r3b can be joined with tbl_gst_rtn_r3b.idtbl_gst_rtn_r3b
-- tbl_gst_rtn_r3b_tx_pmt_pd_cash.idtbl_gst_rtn_r3b_tx_pmt can be joined with tbl_gst_rtn_r3b_tx_pmt.idtbl_gst_rtn_r3b_tx_pmt
-- tbl_gst_rtn_r3b_tx_pmt_pd_itc.idtbl_gst_rtn_r3b_tx_pmt can be joined with tbl_gst_rtn_r3b_tx_pmt.idtbl_gst_rtn_r3b_tx_pmt
