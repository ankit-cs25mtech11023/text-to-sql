-- ============================================================
-- Schema: public
-- Module: EWB (E-Way Bill — statutory document for goods movement)
-- Description: Captures consignments, items, transporters, vehicles,
--              cancellations, rejections, and validity extensions for
--              taxpayer goods movements. Two parallel sub-modules:
--                Part-A : the e-way bill itself (header + items)
--                Part-B : vehicle / transporter / cancel / reject /
--                         extend events on the e-way bill
--
-- Tables (brief):
-- 1) public.tbl_ewb_parta                    -- Part-A parent (one row per processed batch: state, period, category)
-- 2) public.tbl_ewb_parta_ewb                -- MAIN PART-A TABLE — one row per e-way bill (frgstin, togstin, ewbno, ewbdt, values)
-- 3) public.tbl_ewb_parta_ewb_itemlist       -- Item-level lines within each Part-A EWB (HSN, qty, rates, amounts)
-- 4) public.tbl_ewb_partb                    -- Part-B parent (one row per processed batch: state, period, category)
-- 5) public.tbl_ewb_partb_ewb                -- MAIN PART-B TABLE — one row per EWB Part-B (ewb_no, fin_valid_dt)
-- 6) public.tbl_ewb_partb_ewb_partbdet       -- Vehicle / transport-mode / Part-B update details
-- 7) public.tbl_ewb_partb_ewb_canceldet      -- EWB cancellation events
-- 8) public.tbl_ewb_partb_ewb_extenddet      -- EWB validity extension events
-- 9) public.tbl_ewb_partb_ewb_rejdtl         -- EWB rejection events (rejected by counterparty GSTIN)
-- 10) public.tbl_ewb_partb_ewb_transdet      -- Transporter assignment / change events
-- ============================================================

CREATE TABLE public.tbl_ewb_parta (  -- PART-A PARENT TABLE — represents one processed batch of Part-A e-way bills (per state, period, category). Detail rows in tbl_ewb_parta_ewb roll up here via idtbl_ewb_parta.
  idtbl_ewb_parta BIGINT PRIMARY KEY, -- Primary key
  statecode VARCHAR, -- Numeric state code as string. Sample: "3" (=Punjab), "6" (=Haryana), "8" (=Rajasthan), "24" (=Gujarat).
  statename VARCHAR, -- Uppercase state name. Sample: "PUNJAB", "HARYANA", "RAJASTHAN".
  category VARCHAR, -- Batch category. Sample: "PARTA" (regular feed) or "PARTB".
  period TEXT, -- Return period in MMYYYY format when populated; OFTEN EMPTY in data. Prefer procdate for filtering.
);

CREATE TABLE public.tbl_ewb_parta_ewb (  -- MAIN PART-A TABLE for e-way bills. JOIN THIS TABLE FOR ALL QUERIES needing taxpayer (consignor/consignee), invoice value, distance, or EWB identifier. This is the ONLY table with frgstin, togstin, ewbno.
  idtbl_ewb_parta_ewb BIGINT PRIMARY KEY, -- Primary key
  ewbno VARCHAR UNIQUE, -- 12-digit E-Way Bill number assigned by NIC portal. Unique per Part-A row (one row per e-way bill). Sample: "392234145276", "392234143845".
  ewbdt VARCHAR, -- E-Way Bill generation timestamp in DD/MM/YYYY HH:MM:SS AM/PM. Sample: "20/04/2026 11:52:00 PM".
  usertyp VARCHAR, -- LLM-HIDE User type that generated the EWB.
  usergstin VARCHAR, -- 15-char GSTIN of the user that generated the EWB. Sample: "06AAECM0000F1ZK".
  transtyp VARCHAR, -- Transaction type code (numeric string). Sample: "1" (=Regular), "2" (=Bill To-Ship To), "3" (=Bill From-Dispatch From), "4" (=Combination of 2 and 3).
  suptype VARCHAR, -- Supply direction. Sample: "O" (=Outward / sale), "I" (=Inward / purchase).
  ssuptyp VARCHAR, -- Sub-supply type code (numeric string, OFTEN PADDED with trailing spaces). Sample: "1  " (=Supply), "8  " (=Others). Trim before comparing or use LIKE.
  doctyp VARCHAR, -- Document type backing the EWB. Sample: "INV" (=Tax Invoice), "CHL" (=Delivery Challan), "BIL" (=Bill of Supply).
  docno VARCHAR, -- Source document number (free-form). Sample: "HRDC-2627-50", "J06KIR04260005PS".
  docdt VARCHAR, -- Source document date in DD/MM/YYYY. Sample: "20/04/2026".
  frgstin VARCHAR, -- 15-char Consignor (seller / sender) GSTIN. Sample: "06AAECM0000F1ZK". Use for outgoing-movement queries. JOINS to tbl_gst_rtn_r3b.gstin (cross-module bridge).
  frname VARCHAR, -- Consignor trade name. Sample: "Manikaran Power Limited", "ZEPTO LIMITED".
  frplac VARCHAR, -- Consignor place — usually city/district, sometimes the state name. Sample: "Haryana", "Jhajjar".
  frpin VARCHAR, -- Consignor PIN code (6 digits). Sample: "125077", "124108".
  frstat VARCHAR, -- Consignor state code (numeric string). Sample: "6" (=Haryana), "3" (=Punjab).
  togstin VARCHAR, -- 15-char Consignee (receiver / buyer) GSTIN. Sample: "03AACCN0000H1ZW". JOINS to tbl_gst_rtn_r3b.gstin (cross-module bridge).
  toname VARCHAR, -- Consignee trade name. Sample: "NabhaPowerLimitedPPL".
  toplac VARCHAR, -- Consignee place. Sample: "Punjab", "Patiala".
  topin VARCHAR, -- Consignee PIN code. Sample: "140401", "140417".
  tostat VARCHAR, -- Consignee state code (numeric). Sample: "3" (=Punjab).
  assval NUMERIC, -- Total assessable (taxable) value, pre-tax. Sample: 208700.78, 6756.03.
  cgstval NUMERIC, -- Total CGST on the EWB. ZERO for inter-state movements (where IGST applies instead).
  sgstval NUMERIC, -- Total SGST/UTGST on the EWB. ZERO for inter-state movements.
  igstval NUMERIC, -- Total IGST on the EWB. NONZERO for inter-state movements (frstat <> tostat). Sample: 10435.04, 504.18.
  cessval NUMERIC, -- Total advalorem cess on the EWB. Often 0.
  cessnonadvolval NUMERIC, -- LLM-HIDE Total non-advalorem (specific/per-unit) cess. Often 0.
  otherval NUMERIC, -- Other value (rounding / misc). Often 0.
  status VARCHAR, -- Current EWB status. Sample: "ACT" (=Active), "CNL" (=Cancelled), "EXP" (=Expired).
  rejstatus VARCHAR, -- Rejection status flag. Empty/blank when not rejected; non-empty when the consignee has rejected the EWB.
  travdist VARCHAR, -- Travel distance declared in km (stored as STRING). Sample: "232", "267".
  ssupdesc VARCHAR, -- Sub-supply description (free-text, OFTEN BLANK). Sample: "Others".
  "InvVal" NUMERIC, -- Invoice value (gross, including tax). Sample: 219135.82, 7260.15. CASE-SENSITIVE column name — must always be referenced with double quotes ("InvVal"), otherwise PostgreSQL folds to lowercase and the column is not found.
  ewbvaliddt VARCHAR, -- EWB validity expiry timestamp in DD/MM/YYYY HH:MM:SS AM/PM. Sample: "22/04/2026 11:59:59 PM".
  vehtype VARCHAR, -- Vehicle type. Sample: "R" (=Regular), "O" (=ODC = Over Dimensional Cargo).
  despfrstat VARCHAR, -- Dispatched-from state code (numeric). May differ from frstat for Bill-To/Ship-To transactions. Sample: "6".
  shiptostat VARCHAR, -- Ship-to state code (numeric). May differ from tostat for Bill-To/Ship-To transactions. Sample: "3".
  idtbl_ewb_parta BIGINT REFERENCES tbl_ewb_parta(idtbl_ewb_parta), -- FK to Part-A parent batch.
  fraddr TEXT, -- Consignor full address (free-text, no fixed schema). Sample: "Khewat No. 752/1154, Murba No. 143/18, ...".
  toaddr TEXT -- Consignee full address (free-text). Sample: "PO Box No. 28, Near Village Nalash, ...".
);

CREATE TABLE public.tbl_ewb_parta_ewb_itemlist (  -- Item-level lines within each Part-A e-way bill. One row per HSN/item line in the consignment. JOIN through idtbl_ewb_parta_ewb to tbl_ewb_parta_ewb to reach taxpayer info.
  idtbl_ewb_parta_ewb_itemlist BIGINT PRIMARY KEY, -- Primary key
  itemno VARCHAR, -- Line number within the EWB (string). Sample: "1", "13", "14".
  prodnam VARCHAR, -- Product / item name (free-text, OFTEN BLANK in data). Sample: "Bio Fuel Pellets 8MM - 3400 GCV".
  hsncod VARCHAR, -- HSN / SAC classification code. Sample: "44013100" (Wood pellets), "20098910", "11010000".
  qty VARCHAR, -- Quantity shipped (stored as STRING, may be decimal). Sample: "29.43", "12", "2".
  "QtyUqc" VARCHAR, -- Unit of measure (Quantity Unit Code). Sample: "MTS" (metric tonnes), "PCS" (pieces), "KGS", "NOS", "MTR". Case-sensitive — quote when referencing.
  cgstrt NUMERIC, -- CGST rate applied to this item (percent).
  sgstrt NUMERIC, -- SGST rate applied to this item (percent).
  igstrt NUMERIC, -- IGST rate applied to this item (percent). Sample: 5, 12, 18, 28. 0 for intra-state.
  cessrt NUMERIC, -- Cess rate applied to this item (percent).
  assamt NUMERIC, -- Assessable (taxable) amount for this line. Sample: 208700.78, 820.04.
  cessadvol NUMERIC, -- LLM-HIDE Advalorem cess amount for this item line.
  cessnonadvol NUMERIC, -- LLM-HIDE Non-advalorem (specific) cess amount for this item line.
  idtbl_ewb_parta_ewb BIGINT REFERENCES tbl_ewb_parta_ewb(idtbl_ewb_parta_ewb), -- FK to Part-A main table. MUST JOIN through this for taxpayer/period info.
);

CREATE TABLE public.tbl_ewb_partb (  -- PART-B PARENT TABLE — represents one processed batch of Part-B events (per state, period, category). Detail rows in tbl_ewb_partb_ewb roll up here via idtbl_ewb_partb.
  ididtbl_ewb_partb BIGINT PRIMARY KEY, -- Primary key (note the doubled "id" prefix — this is the actual column name in source DB).
  statecode VARCHAR, -- Numeric state code as string. Sample: "3" (=Punjab).
  statename VARCHAR, -- Uppercase state name. Sample: "PUNJAB".
  category VARCHAR, -- Batch category. Sample: "PARTB" (regular) or "PARTB".
  period TEXT, -- Return period (MMYYYY) when populated; OFTEN EMPTY. Prefer procdate.
);

CREATE TABLE public.tbl_ewb_partb_ewb (  -- MAIN PART-B TABLE for e-way bills. One row per Part-B event packet (validity / vehicle / cancel / etc.). Linked LOGICALLY to Part-A via ewb_no = tbl_ewb_parta_ewb.ewbno (no enforced FK between parts).
  idtbl_ewb_partb_ewb BIGINT PRIMARY KEY, -- Primary key
  ewb_no VARCHAR, -- 12-digit E-Way Bill number. Sample: "771625663090". Use ewb_no = tbl_ewb_parta_ewb.ewbno to bridge Part-A and Part-B.
  fin_valid_dt VARCHAR, -- Final validity date for the EWB in DD/MM/YYYY HH:MM:SS AM/PM. Sample: "20/04/2026 11:59:59 PM".
  idtbl_ewb_partb BIGINT REFERENCES tbl_ewb_partb(ididtbl_ewb_partb), -- FK to Part-B parent batch.
);

CREATE TABLE public.tbl_ewb_partb_ewb_partbdet (  -- Vehicle and transport detail per Part-B EWB. Multiple rows per EWB are possible when the vehicle/transporter changes mid-route.
  idtbl_ewb_partb_ewb_partbdet BIGINT PRIMARY KEY, -- Primary key
  vehno VARCHAR, -- Vehicle registration number (Indian RTO format). Sample: "PB10KB0326", "RJ23GC4575", "GJ27TG8978".
  frplace VARCHAR, -- From place for this leg (mixed granularity in data: state, district, city, or free-text). Sample: "PUNJAB", "NAGAUR", "DIST BEAWAR  RAJASTHAN", "punjabi bagh bkg dly".
  reascd VARCHAR, -- Reason code for this Part-B update (first-vehicle / mid-journey / ...). Often blank in data.
  trdocno VARCHAR, -- Transporter document number (LR/AWB/RR). Often blank. Sample: "17709636".
  updid VARCHAR, -- 15-char GSTIN of the user who uploaded this update. Sample: "88AAECS0000H1ZA", "08AAACG9999P1Z7".
  upddt VARCHAR, -- Upload timestamp DD/MM/YYYY HH:MM:SS AM/PM. Sample: "20/04/2026 07:44:00 AM".
  transmode VARCHAR, -- Mode of transport code (numeric, OFTEN PADDED with trailing spaces). Sample: "1  " (=Road), "2  " (=Rail), "3  " (=Air), "4  " (=Ship). Trim or use LIKE.
  trdocdt VARCHAR, -- Transporter document date DD/MM/YYYY. Often blank. Sample: "17/04/2026 12:00:00 AM".
  idtbl_ewb_partb_ewb BIGINT REFERENCES tbl_ewb_partb_ewb(idtbl_ewb_partb_ewb), -- FK to Part-B main table.
  ewb_no VARCHAR, -- Denormalized EWB number (FREQUENTLY BLANK — get from parent tbl_ewb_partb_ewb.ewb_no instead).
  valid_till_dt TEXT, -- Validity-till date for this leg DD/MM/YYYY HH:MM:SS AM/PM. Often blank.
);

CREATE TABLE public.tbl_ewb_partb_ewb_canceldet (  -- Cancellation events on an EWB. Holds when, why and by whom an EWB was cancelled.
  idtbl_ewb_partb_ewb_canceldet BIGINT PRIMARY KEY, -- Primary key
  ewb_no TEXT, -- Cancelled EWB number (denormalized). FREQUENTLY BLANK in data — JOIN through idtbl_ewb_partb_ewb to get it from tbl_ewb_partb_ewb.ewb_no.
  canceldt TEXT, -- Cancellation timestamp DD/MM/YYYY HH:MM:SS AM/PM. Sample: "18/04/2026 10:38:00 PM".
  cancelreascd TEXT, -- Cancellation reason code (numeric string). Sample: "3" (=Duplicate), "4" (=Data entry error / Wrong entry).
  cancelreasrem TEXT, -- Free-text cancellation remark. Sample: "Wrong Site selected", "Rates Wrong", "Transporter Missing". Often blank.
  cancelby TEXT, -- 15-char GSTIN that cancelled the EWB. Sample: "07CNUPN0000R1ZP", "08AAACK0000N1Z0".
  idtbl_ewb_partb_ewb BIGINT REFERENCES tbl_ewb_partb_ewb(idtbl_ewb_partb_ewb), -- FK to Part-B main table.
);

CREATE TABLE public.tbl_ewb_partb_ewb_extenddet (  -- Validity-extension events on an EWB. Captures legitimate delays where the transporter/taxpayer extended the valid-till date.
  idtbl_ewb_partb_ewb_extenddet BIGINT PRIMARY KEY, -- Primary key
  extdt VARCHAR, -- Extension request timestamp DD/MM/YYYY HH:MM:SS AM/PM. Sample: "19/04/2026 09:23:00 PM".
  extreascd VARCHAR, -- Extension reason code (numeric string). Sample: "4" (=Delay), "99" (=Others).
  extreasrem VARCHAR, -- Free-text extension remark. Sample: "Delay", "wait for unloading", "gh".
  extby VARCHAR, -- Extension actor — usually a username or system handle (NOT always a GSTIN). Sample: "lmrc010989", "Bansal@roadline".
  frplace VARCHAR, -- Current location at extension time (city/town, free-text). Sample: "Ambala", "bhatinda", "BHATINDA".
  remdist VARCHAR, -- Remaining distance to destination in km (stored as STRING). Sample: "17", "147", "100".
  prev_validdt VARCHAR, -- Previous validity date before the extension DD/MM/YYYY HH:MM:SS AM/PM. Sample: "20/04/2026 11:59:59 PM".
  frstat VARCHAR, -- Current state code (numeric string). Sample: "3" (=Punjab), "6" (=Haryana), "8" (=Rajasthan).
  idtbl_ewb_partb_ewb BIGINT REFERENCES tbl_ewb_partb_ewb(idtbl_ewb_partb_ewb), -- FK to Part-B main table.
  ewb_no TEXT, -- Denormalized EWB number — FREQUENTLY BLANK. JOIN through tbl_ewb_partb_ewb for the actual EWB number.
);

CREATE TABLE public.tbl_ewb_partb_ewb_rejdtl (  -- Rejection events: when the counterparty GSTIN rejects an EWB. Used to detect disputed / refused consignments.
  idtbl_ewb_partb_ewb_rejdtl BIGINT PRIMARY KEY, -- Primary key
  ewb_no TEXT, -- Rejected EWB number (denormalized) — FREQUENTLY BLANK. JOIN through tbl_ewb_partb_ewb.
  rejgstin TEXT, -- 15-char GSTIN that rejected the EWB (counterparty). Sample: "05AYXPR0000P1ZC", "06AAACK0000K1ZF".
  rejdt TEXT, -- Rejection timestamp DD/MM/YYYY HH:MM:SS AM/PM. Sample: "20/04/2026 01:19:49 PM".
  idtbl_ewb_partb_ewb BIGINT REFERENCES tbl_ewb_partb_ewb(idtbl_ewb_partb_ewb), -- FK to Part-B main table.
);

CREATE TABLE public.tbl_ewb_partb_ewb_transdet (  -- Transporter assignment / change events on an EWB. Captures when a new transporter is assigned (transid) or an upload is recorded.
  idtbl_ewb_partb_ewb_transdet BIGINT PRIMARY KEY, -- Primary key
  transid VARCHAR, -- 15-char GSTIN of the newly assigned transporter. Sample: "88AAECS0000H1ZA", "08AAICK0000B1ZE".
  updid VARCHAR, -- Uploader identifier — usually an API/system handle PADDED WITH TRAILING SPACES, sometimes a GSTIN. Sample: "API_NBC_RJ  ", "API_AMBUJACEMENTLTD ", "ULTRATECH   ", "07AHGPK0000D1ZT     ". Trim before comparing.
  upddt VARCHAR, -- Upload timestamp DD/MM/YYYY HH:MM:SS AM/PM. Sample: "17/04/2026 01:42:00 PM".
  idtbl_ewb_partb_ewb BIGINT REFERENCES tbl_ewb_partb_ewb(idtbl_ewb_partb_ewb), -- FK to Part-B main table.
  ewb_no TEXT, -- LLM-HIDE Denormalized EWB number — FREQUENTLY BLANK. JOIN through tbl_ewb_partb_ewb.
);

-- ============================================================
-- JOIN HINTS FOR SQL GENERATION
-- Intra-module FK paths. Two trees:
--   Part-A:  tbl_ewb_parta -> tbl_ewb_parta_ewb -> tbl_ewb_parta_ewb_itemlist
--   Part-B:  tbl_ewb_partb -> tbl_ewb_partb_ewb -> {partbdet, canceldet,
--                                                   extenddet, rejdtl, transdet}
-- The two trees are connected LOGICALLY by ewb_no (text):
--   tbl_ewb_parta_ewb.ewbno = tbl_ewb_partb_ewb.ewb_no
-- ============================================================

-- Join hints:
-- tbl_ewb_parta_ewb.idtbl_ewb_parta can be joined with tbl_ewb_parta.idtbl_ewb_parta
-- tbl_ewb_parta_ewb_itemlist.idtbl_ewb_parta_ewb can be joined with tbl_ewb_parta_ewb.idtbl_ewb_parta_ewb
-- tbl_ewb_partb_ewb.idtbl_ewb_partb can be joined with tbl_ewb_partb.ididtbl_ewb_partb
-- tbl_ewb_partb_ewb_partbdet.idtbl_ewb_partb_ewb can be joined with tbl_ewb_partb_ewb.idtbl_ewb_partb_ewb
-- tbl_ewb_partb_ewb_canceldet.idtbl_ewb_partb_ewb can be joined with tbl_ewb_partb_ewb.idtbl_ewb_partb_ewb
-- tbl_ewb_partb_ewb_extenddet.idtbl_ewb_partb_ewb can be joined with tbl_ewb_partb_ewb.idtbl_ewb_partb_ewb
-- tbl_ewb_partb_ewb_rejdtl.idtbl_ewb_partb_ewb can be joined with tbl_ewb_partb_ewb.idtbl_ewb_partb_ewb
-- tbl_ewb_partb_ewb_transdet.idtbl_ewb_partb_ewb can be joined with tbl_ewb_partb_ewb.idtbl_ewb_partb_ewb
-- tbl_ewb_parta_ewb.ewbno can be joined with tbl_ewb_partb_ewb.ewb_no
