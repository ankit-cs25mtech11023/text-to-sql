-- ============================================================
-- Schema: public
-- Module: GSTR-7 (TDS Return — Tax Deducted at Source under GST)
-- Description: Filed by DEDUCTORS (typically govt depts, PSUs, large
--              entities) who deduct GST-TDS from payments to
--              suppliers. Captures: who filed (gstin = deductor),
--              for which return period (fp), how much TDS was
--              deducted from each deductee (gstin_ded), invoice-level
--              breakdowns, amendments to prior periods (TDSA), and
--              the resulting tax-payable / tax-paid settlements.
--
-- KEY DOMAIN CONTRASTS (cross-cutting; not stated at column level):
-- - DEDUCTOR vs DEDUCTEE: tbl_gst_rtn_r7.gstin is the FILER (deductor).
--   Detail tables carry gstin_ded = the DEDUCTEE (supplier whose
--   payment had TDS withheld). Filter on gstin for "TDS deducted BY X";
--   on gstin_ded for "TDS deducted FROM X". Do NOT conflate.
-- - Tax-payable (tbl_gst_rtn_r7_tax_pay) is declared liability.
--   Tax-paid (tbl_gst_rtn_r7_tax_paid_pd_by_cash, joined via
--   tbl_gst_rtn_r7_tax_paid) is actual settlement of that liability.
--
-- Tables (brief):
-- 1) public.tbl_gst_rtn_r7                       -- MAIN TABLE — has gstin (deductor) and fp (period)
-- 2) public.tbl_gst_rtn_r7_tds                   -- TDS deductee-wise totals for the return
-- 3) public.tbl_gst_rtn_r7_tds_inv               -- TDS invoice-wise breakdown (under each TDS row)
-- 4) public.tbl_gst_rtn_r7_tdsa                  -- TDS Amendments (revisions to prior periods)
-- 5) public.tbl_gst_rtn_r7_tdsa_inv              -- TDSA invoice-wise breakdown
-- 6) public.tbl_gst_rtn_r7_tax_pay               -- Tax payable (declared liability per liab_id)
-- 7) public.tbl_gst_rtn_r7_tax_paid              -- Parent join table for tax-paid settlements
-- 8) public.tbl_gst_rtn_r7_tax_paid_pd_by_cash   -- Tax actually paid via cash ledger
-- ============================================================

-- MAIN TABLE for GSTR-7 returns. JOIN THIS TABLE FOR ALL QUERIES needing the deductor's GSTIN or the return period. UNIQUE(gstin, fp).
CREATE TABLE public.tbl_gst_rtn_r7 (
  idtbl_gst_rtn_r7 BIGINT PRIMARY KEY, -- Primary key (internal identity).
  fp VARCHAR, -- Return Period in MMYYYY format. Sample: "102018" (=Oct 2018), "042019" (=Apr 2019). YEAR=last 4 chars, MONTH=first 2. For "year 2019" use fp LIKE '%2019'. For "April" use fp LIKE '04%'. NEVER use equality for year-only filters.
  gstin VARCHAR, -- 15-char Deductor GSTIN — the filer of this R7 return. Sample: "03AABCP9999J2DM". First 2 chars = state code. This column ONLY exists in this main table. For counting deductors use COUNT(DISTINCT gstin).
  fil_dt VARCHAR, -- Filing Date in DD-MM-YYYY format. Sample: "29-11-2018", "18-05-2019". VARCHAR string; use TO_DATE(fil_dt, 'DD-MM-YYYY') for date math.
  inserted_date TIMESTAMPTZ, -- Row ingestion timestamp. Sample: "2023-11-28 12:29:06.823828+05:30". Operational column — usually NOT what users mean by "filed on".
);

-- TDS data: one row per DEDUCTEE per return. amt_ded = gross amount paid to the deductee on which TDS was deducted. The IGST/CGST/SGST split below describes the tax that was withheld. JOIN through tbl_gst_rtn_r7 (idtbl_gst_rtn_r7) to reach the deductor's gstin and the return period.
CREATE TABLE public.tbl_gst_rtn_r7_tds (
  idtbl_gst_rtn_r7_tds BIGINT PRIMARY KEY, -- Primary key
  gstin_ded TEXT, -- 15-char DEDUCTEE GSTIN — the supplier whose payment was subject to TDS. Sample: "19AABCK9999C1ZI" (state 19 = West Bengal), "03AADFP9999Q1ZR". DO NOT confuse with the deductor's gstin in the main table.
  amt_ded NUMERIC, -- Amount paid to deductee on which tax was deducted (gross, pre-TDS). Sample: 7669081.00, 2191166.00, 500000.00.
  iamt NUMERIC, -- IGST withheld. Sample: 153381.62, 43823.32. 
  camt NUMERIC, -- CGST withheld. Sample: 5000.00, 8060.00, 8519.00.
  samt NUMERIC, -- SGST withheld.
  chksum TEXT, -- LLM-HIDE Source-feed checksum (sha256 hex) for this row. Operational; not used in user queries.
  tbl_gst_rtn_r7 BIGINT REFERENCES tbl_gst_rtn_r7(idtbl_gst_rtn_r7), -- FK to main table. NOTE: the FK column is named `tbl_gst_rtn_r7` (no `id` prefix) — quirk of the source DB. Use this exact name in JOIN ON clauses.
  inserted_date TIMESTAMPTZ, -- Row ingestion timestamp. Sample: "2023-11-28 12:29:06.830804+05:30".
  deductee_name TEXT, -- Trade name of the deductee (often blank in older data; populated more reliably on recent rows).
  idt TEXT, -- Invoice date in DD-MM-YYYY (often blank on older TDS rows; invoice details typically live in tbl_gst_rtn_r7_tds_inv instead).
  inum TEXT, -- Invoice number (often blank on older TDS rows; see tds_inv).
  ival TEXT -- Invoice value (often blank on older TDS rows; see tds_inv).
);

-- TDS invoice-level breakdown: one row per invoice line under a TDS deductee row. Amounts here detail the deduction at invoice granularity. JOIN through idtbl_gst_rtn_r7_tds to tbl_gst_rtn_r7_tds for the deductee, then to main for deductor/period.
CREATE TABLE public.tbl_gst_rtn_r7_tds_inv (
  idtbl_gst_rtn_r7_tds_inv BIGINT PRIMARY KEY, -- Primary key
  inum TEXT, -- Invoice number (free-form). Sample: "498", "61", "ME/25-26/464", "TI/25-26/229", "AV/25-26/30". May be purely numeric or alphanumeric.
  idt TEXT, -- Invoice date in DD-MM-YYYY. Sample: "29-09-2025", "13-09-2025", "26-08-2025".
  ival NUMERIC, -- Invoice value (gross). Sample: 202707, 518149, 1024634, 794958.
  amt_ded NUMERIC, -- Amount on the invoice on which TDS was deducted. Sample: 170085, 439110, 868333.5.
  iamt NUMERIC, -- IGST withheld for this invoice.
  camt NUMERIC, -- CGST withheld.
  samt NUMERIC, -- SGST withheld.
  flag TEXT, -- Per-row flag (observed: "N","Y" or blank). Meaning is feed-specific.
  chksum TEXT, -- LLM-HIDE Source-feed checksum (sha256 hex) for this row.
  idtbl_gst_rtn_r7_tds BIGINT REFERENCES tbl_gst_rtn_r7_tds(idtbl_gst_rtn_r7_tds), -- FK to TDS parent row.
  inserted_date TIMESTAMPTZ -- Row ingestion timestamp. Sample: "2025-10-14 12:12:23.991941+05:30".
);

-- TDS Amendment data: revisions to TDS rows reported in PRIOR return periods. Each row carries BOTH the original (`o*`) values and the revised values. The original period is in `omonth` (MMYYYY). The amendment itself belongs to the return period of the parent tbl_gst_rtn_r7.fp. Use this table for "TDS corrections / amendments" questions.
CREATE TABLE public.tbl_gst_rtn_r7_tdsa (
  idtbl_gst_rtn_r7_tdsa BIGINT PRIMARY KEY, -- Primary key
  ogstin_ded TEXT, -- ORIGINAL deductee GSTIN as previously reported. Sample: "27AAACC9999G1ZD", "03AABFV9999G1ZG". May be empty when only amount was amended.
  omonth TEXT, -- ORIGINAL return period being amended, in MMYYYY. Sample: "102019" (=Oct 2019), "042019", "052019".
  oamt_ded NUMERIC, -- ORIGINAL amount on the invoice on which TDS was deducted as previously reported. Sample: 745050.96, 1201619.
  gstin_ded TEXT, -- REVISED deductee GSTIN (the corrected value). Sample: "03APEPG9999F1ZI" when changed; or same as ogstin_ded when only the amount was corrected.
  amt_ded NUMERIC, -- REVISED amount on the invoice on which TDS was deducted. Sample: 745050.96, 1201619.00.
  iamt NUMERIC, -- REVISED IGST withheld. Sample: 14900.00.
  camt NUMERIC, -- REVISED CGST withheld. Sample: 12016.19.
  samt NUMERIC, -- REVISED SGST withheld.
  chksum TEXT, -- LLM-HIDE Source-feed checksum.
  source TEXT, -- Source code of the amendment (observed values: "C", "D"). Feed-specific code; meaning not authoritatively documented in this catalog. If a query needs to discriminate amendment types, ask the user to clarify.
  act_tkn TEXT, -- Action-taken flag (observed: "Y", "N").
  tbl_gst_rtn_r7 BIGINT REFERENCES tbl_gst_rtn_r7(idtbl_gst_rtn_r7), -- FK to main table (note: column name is `tbl_gst_rtn_r7`, not `idtbl_gst_rtn_r7` — same quirk as the TDS table).
  inserted_date TIMESTAMPTZ, -- Row ingestion timestamp.
  deductee_name TEXT, -- Revised deductee trade name (often blank on older rows).
  idt TEXT, -- Revised invoice date DD-MM-YYYY (often blank — see tdsa_inv).
  inum TEXT, -- Revised invoice number (often blank — see tdsa_inv).
  ival TEXT, -- Revised invoice value (often blank — see tdsa_inv).
  odeductee_name TEXT, -- ORIGINAL deductee trade name (often blank).
  oidt TEXT, -- ORIGINAL invoice date DD-MM-YYYY (often blank).
  oinum TEXT, -- ORIGINAL invoice number (often blank).
  oival TEXT -- ORIGINAL invoice value (often blank).
);

-- TDSA invoice-level breakdown. Mirrors tds_inv but carries ORIGINAL (`o*`) and REVISED columns side by side. JOIN through idtbl_gst_rtn_r7_tdsa to tbl_gst_rtn_r7_tdsa.
CREATE TABLE public.tbl_gst_rtn_r7_tdsa_inv (
  idtbl_gst_rtn_r7_tdsa_inv BIGINT PRIMARY KEY, -- Primary key
  ogstin_ded TEXT, -- ORIGINAL deductee GSTIN (often blank in samples).
  omonth TEXT, -- ORIGINAL period MMYYYY (often blank in samples — already carried on the parent tdsa row).
  oamt_ded NUMERIC, -- ORIGINAL amount deducted on the invoice. Sample: 486780, 569620, 51934.
  gstin_ded TEXT, -- REVISED deductee GSTIN (often blank when only amount was amended).
  amt_ded NUMERIC, -- REVISED amount deducted on the invoice. Sample: 486780, 569620, 51934.
  iamt NUMERIC, -- REVISED IGST withheld for this invoice.
  camt NUMERIC, -- REVISED CGST withheld. Sample: 4867.8, 5696.2, 3175.
  samt NUMERIC, -- REVISED SGST withheld.
  chksum TEXT, -- LLM-HIDE Source-feed checksum.
  source TEXT, -- Source code (observed: "C", "D" — feed-specific; meaning not documented).
  act_tkn TEXT, -- Action-taken flag (observed: "Y", "N").
  oinum TEXT, -- ORIGINAL invoice number. Sample: "2300", "2314", "211", "TI/25-26/62", "TI/25-26/63".
  oidt TEXT, -- ORIGINAL invoice date DD-MM-YYYY. Sample: "26-09-2025", "27-09-2025", "02-09-2025".
  oival TEXT, -- ORIGINAL invoice value (stored as TEXT here, unlike tds_inv.ival which is NUMERIC). Sample: "496516", "581012", "61282".
  inum TEXT, -- REVISED invoice number. Often equals oinum when only amount was corrected. Sample: "2300", "TI/25-26/62".
  idt TEXT, -- REVISED invoice date DD-MM-YYYY. Often equals oidt.
  ival TEXT, -- REVISED invoice value (TEXT). Often equals oival when only amount was corrected.
  idtbl_gst_rtn_r7_tdsa BIGINT REFERENCES tbl_gst_rtn_r7_tdsa(idtbl_gst_rtn_r7_tdsa), -- FK to TDSA parent row.
  inserted_date TIMESTAMPTZ -- Row ingestion timestamp.
);

-- Tax PAYABLE — declared liability for the return. Multiple rows per return (one per liab_id). The igst_*/cgst_*/sgst_*/cess_* columns break the liability into tax / interest / penalty / fee / others, with `*_tot` as the row's total. JOIN through tbl_gst_rtn_r7 (idtbl_gst_rtn_r7) for deductor/period.
CREATE TABLE public.tbl_gst_rtn_r7_tax_pay (  
  idtbl_gst_rtn_r7_tax_pay BIGINT PRIMARY KEY, -- Primary key
  liab_id TEXT, -- Liability ID (numeric string). Sample: "227462490", "111076359", "233749684". Sequential identifier per liability obligation.
  trancd TEXT, -- Transaction code. Sample: "30002" (consistent with R3B's "regular tax payment" code).
  trandate TEXT, -- Transaction date in DD-MM-YYYY. Sample: "11-01-2020", "29-11-2018".
  igst_tx NUMERIC, -- IGST tax payable. Sample: 197205.00 (inter-state liability); 0.00 otherwise.
  igst_intr NUMERIC, -- IGST interest payable.
  igst_pen NUMERIC, -- IGST penalty payable. 
  igst_fee NUMERIC, -- IGST late-filing fee payable. 
  igst_oth NUMERIC, -- IGST others payable. 
  igst_tot NUMERIC, -- LLM-HIDE IGST total payable (= sum of the IGST tx/intr/pen/fee/oth on this row).
  cgst_tx NUMERIC, -- CGST tax payable. Sample: 34775.00, 31183.00, 108377.00.
  cgst_intr NUMERIC, -- CGST interest payable.
  cgst_pen NUMERIC, -- CGST penalty payable. 
  cgst_fee NUMERIC, -- CGST late-filing fee payable. Sample: 100.00, 1200.00; 
  cgst_oth NUMERIC, -- CGST others payable. 
  cgst_tot NUMERIC, -- LLM-HIDE CGST total payable.
  sgst_tx NUMERIC, -- SGST tax payable.
  sgst_intr NUMERIC, -- SGST interest payable.
  sgst_pen NUMERIC, -- SGST penalty payable.
  sgst_fee NUMERIC, -- SGST late-filing fee payable.
  sgst_oth NUMERIC, -- SGST others payable.
  sgst_tot NUMERIC, -- LLM-HIDE SGST total payable.
  cess_tx NUMERIC, -- Cess tax payable.
  cess_intr NUMERIC, -- Cess interest.
  cess_pen NUMERIC, -- Cess penalty.
  cess_fee NUMERIC, -- Cess late-filing fee.
  cess_oth NUMERIC, -- Cess others.
  cess_tot NUMERIC, -- LLM-HIDE Cess total.
  tbl_gst_rtn_r7 BIGINT REFERENCES tbl_gst_rtn_r7(idtbl_gst_rtn_r7), -- FK to main table (column name is `tbl_gst_rtn_r7` — same FK-naming quirk as TDS / TDSA).
  inserted_date TIMESTAMPTZ -- Row ingestion timestamp.
);

-- Parent JOIN TABLE for tax-paid settlements. Holds no payment data itself; bridges tbl_gst_rtn_r7 to the per-mode payment detail tables (currently only pd_by_cash). One row per return per payment block.
CREATE TABLE public.tbl_gst_rtn_r7_tax_paid (
  idtbl_gst_rtn_r7_tax_paid BIGINT PRIMARY KEY, -- Primary key
  tbl_gst_rtn_r7 BIGINT REFERENCES tbl_gst_rtn_r7(idtbl_gst_rtn_r7), -- FK to main table (`tbl_gst_rtn_r7` column name — FK-naming quirk).
  inserted_date TIMESTAMPTZ -- Row ingestion timestamp.
);

-- Tax actually PAID via cash ledger — settlement records against the liabilities declared in tbl_gst_rtn_r7_tax_pay. Multiple rows per return (one per debit_id). Same igst/cgst/sgst/cess breakdown as tax_pay. JOIN through idtbl_gst_rtn_r7_tax_paid -> tbl_gst_rtn_r7_tax_paid -> tbl_gst_rtn_r7 to reach the deductor and period.
CREATE TABLE public.tbl_gst_rtn_r7_tax_paid_pd_by_cash (
  idtbl_gst_rtn_r7_tax_paid_pd_by_cash BIGINT PRIMARY KEY, -- Primary key
  liab_id TEXT, -- Liability ID being settled. Sample: "243857545", "243859223". Match to tbl_gst_rtn_r7_tax_pay.liab_id when reconciling payable vs paid.
  debit_id TEXT, -- Debit reference ID from the cash ledger. Sample: "DC0302200138755", "DC0307190117451". Format: "DC" + DDMMYY of debit + sequence.
  trancd TEXT, -- Transaction code. Sample: "30002" (regular cash payment).
  trandate TEXT, -- Transaction date in DD-MM-YYYY. Sample: "25-02-2020", "27-07-2019".
  igst_tx NUMERIC, -- IGST tax paid via cash.
  igst_intr NUMERIC, -- IGST interest paid.
  igst_pen NUMERIC, -- IGST penalty paid.
  igst_fee NUMERIC, -- IGST late-filing fee paid.
  igst_oth NUMERIC, -- IGST others paid.
  igst_tot NUMERIC, -- LLM-HIDE IGST total paid (sum of the IGST components on this row).
  cgst_tx NUMERIC, -- CGST tax paid via cash. Sample: 1891.00, 4103.00.
  cgst_intr NUMERIC, -- CGST interest paid.
  cgst_pen NUMERIC, -- CGST penalty paid.
  cgst_fee NUMERIC, -- CGST late-filing fee paid (late-filing fee). Sample: 4600.00, 1500.00, 1400.00.
  cgst_oth NUMERIC, -- CGST others paid.
  cgst_tot NUMERIC, -- LLM-HIDE CGST total paid.
  sgst_tx NUMERIC, -- SGST tax paid.
  sgst_intr NUMERIC, -- SGST interest paid.
  sgst_pen NUMERIC, -- SGST penalty paid.
  sgst_fee NUMERIC, -- SGST late-filing fee paid.
  sgst_oth NUMERIC, -- SGST others paid.
  sgst_tot NUMERIC, -- LLM-HIDE SGST total paid.
  cess_tx NUMERIC, -- Cess tax paid.
  cess_intr NUMERIC, -- Cess interest paid.
  cess_pen NUMERIC, -- Cess penalty paid.
  cess_fee NUMERIC, -- Cess late-filing fee paid.
  cess_oth NUMERIC, -- Cess others paid.
  cess_tot NUMERIC, -- LLM-HIDE Cess total paid.
  idtbl_gst_rtn_r7_tax_paid BIGINT REFERENCES tbl_gst_rtn_r7_tax_paid(idtbl_gst_rtn_r7_tax_paid), -- FK to tax-paid join parent.
  inserted_date TIMESTAMPTZ -- Row ingestion timestamp.
);

-
