-- ============================================================
-- Schema: common  |  Module: GSTREG (Taxpayer Registration & Jurisdiction)
-- (module frame — human doc only; the table comment starts below the blank line)
-- ============================================================

-- MAIN. Taxpayer/GSTIN registration master (dealer master) — ONE ROW PER GSTIN
--   (a plain master table, NOT a partitioned MV). Registration facts: trade /
--   legal name, status, registration & cancellation dates, registration type,
--   constitution of business, contact. Jurisdiction: division -> range -> unit,
--   decoded via the jurisdiction master (mst_state_jurisdiction_code) on stjd.
--   ALSO supplies the geo decode for GSTR-3B: r3b.gstin -> this table -> stjd ->
--   mst_state_jurisdiction_code.state_jur_code -> division / range / unit.
-- --- GENERATOR NOTES (generator only) ---
-- KEY CONVENTIONS (read before generating SQL):
--   * Join the dealer to a fact table on gstin; join the jurisdiction master on
--     t_all_delers_api_v_t.stjd = mst_state_jurisdiction_code.state_jur_code.
--   * To DISPLAY jurisdiction, PROJECT mst_state_jurisdiction_code.division /
--     range / unit (the officer-readable names) — NOT the raw stjd code.
--   * Several columns are coded (authstatus, cobz, psnt, regtypecd, type,
--     regtype). Their decode masters are NOT loaded in this system — read the
--     code per the inline comment; do NOT invent a join to a decode table.
--   * For "active" taxpayers filter canc_dt IS NULL (no cancellation date);
--     "cancelled" taxpayers have canc_dt IS NOT NULL.
-- ============================================================

CREATE TABLE IF NOT EXISTS common.t_all_delers_api_v_t
(
    gstin character varying(30),----GSTIN Number unique Identifier for taxpayer in GST formed from statecode + PAN number; String with 15 character; Sample Value: 29HJKPS9689A8Z5 
    pan_num text,---PAN Number Of Gstin; unique identifier; String with 10 char; Sample Value:AMCPA4567V
    lgnmbzpan character varying,---LEGAL / registered NAME of the business/taxpayer (a firm NAME, per PAN). To filter by a company/firm name, match THIS column with ILIKE (case-insensitive partial), OR'd with trdnm — a firm's name may be recorded as either the legal or the trade name. Sample Value: Rashtriya Ispath Nigam Ltd
    trdnm character varying,---TRADE NAME (brand / operating name) of the business/taxpayer — a firm NAME, NOT a business category. This is the primary column for company/firm/"trade name" filters: match with ILIKE (case-insensitive partial) and OR with lgnmbzpan (the name may sit in either). Sample Value: Vizag Steel
    stcd character varying,--State Code; String with 2 char; Sample Value: 29
    appr_auth character varying(20),--Jurisdiction Belongs Like assigned to STATE or CENTER officials;  Sample Value: CENTER,STATE,null
    stjd character varying,---State jurisdiction code (stjd doesnt tell if the gstin is state or center) Sample Value:GJ063,GJ095
    ctjd character varying,---center jurisdiction code (ctjd doesnt tell if the gstin is state or center) Sample Value:VC0201,WV0203
    rgfmdt date,---GST Registration Start Date
    apprvdt date,---GST Registration Aprroved Date
    apprv_mnth text,---GST Registration Approved Month
    rgtodt date,---GST Registration End Date
    canc_dt date,--GST Cancellation Date if taxapyer cancelled the registration
    canc_mnth text,--GST Registration Cancellation Month
    authstatus character varying,-- Authorization / registration status CODE. Sample: "A" (active), "SC", "CBT". Coded value; its decode master is NOT loaded here — read the code as-is, do NOT invent a join.
    type text,---Migration Type (Ex:C2C--Center to Center , N2C---New to center,S2S -- State to State, N2S --New to State
    ismigrated character varying(20),--Migrated Flag(Ex: Y--Yes, N--No) Migrated from previous tax regime
    regtypecd character varying,--Registration Type code (CA-- Casual Taxpayer,CO--Compostion Taxpayer,ID--ISD taxpayer,NRTP--Non Resident Taxpayer,NT--Normal Taxpayer,REGTM--Temporary Registration,TC--TCS Taxpayer,TD--TDS Taxpayer,TP-- Normal Taxpayer)
    isopcmp character varying,--Is Opted For Composition (O--Opted For Composition ,R-- Regular); String with 1 char(Either  O, R, W,C)
    iscasdl character varying,--Casual dealer/taxpayer Flag (Y--Yes,N--No); String with 1 char(Either ‘Y’ or ‘N’)
    cobz character varying,-- Constitution of business CODE. Sample: "PRO" (proprietorship), "PAR" (partnership), "SCT". Coded value; decode master NOT loaded here — do NOT invent a join.
    psnt character varying,-- Nature of premises possession CODE. Sample: "OWN" (owned), "REN"/"RENT" (rented), "CON" (consent). Coded value; decode master NOT loaded here — do NOT invent a join.
    ntcrbs text,---Nature of core business activity — the business-activity CATEGORY/KIND (e.g. Manufacturer/Retailer/Trader/Wholesaler/Service Provider/Distributor). This is NOT the firm's name — never filter a taxpayer/trade/legal NAME here; use trdnm / lgnmbzpan for names.
    otherntbz text,--Other nature of Bussines activity
    address text,--Address of GSTIN/Taxpayer
    email character varying,--Contact Email of GSTIN/Taxpayer; Sample Value: abc123@gmail.com
    mobile character varying,--Contact Mobile of GSTIN/Taxpayer; Sample Value:9988774455
    inserted_date date,--Data Inserted Date in the table
    regtype character varying,--GST Registation Type(NRTP--Non Resident Taxpayer,O---Opted For Composition,R--Regular,SUO MOTO--Suo Moto ,TCS---TCS,TDS--TDS)
    can_arn text,--GST Registation  cancellation ARN
    can_reasons text,--GST Registation Cancellation Reason
    can_type text,--GST Registation  Cancellation Type (Suo-moto Cancellation  , Voluntary Cancellation)
    optcat text,----Opted Category for Rule 14a(O)
    risk_profile text,---risk profile ("MEDIUM_RISK(5.00)","LOW_RISK(1.00)",'NA')
    -- gstin is 1-row-per-taxpayer (unique). Mark UNIQUE so the fan-out detector
    -- treats the decode join (fact.gstin = gstin) as 1:N, not M:N — no false
    -- fan-out on COUNT/SUM. (UNIQUE, not PRIMARY KEY: the live table declares no
    -- PK; we assert only value-uniqueness, which is all the detector needs.)
    UNIQUE (gstin)
)


-- ============================================================
-- Jurisdiction decode master: state_jur_code -> division / range / unit.
-- 1:1 lookup; LEFT JOIN on t_all_delers_api_v_t.stjd = state_jur_code.
-- ============================================================
CREATE TABLE IF NOT EXISTS common.mst_state_jurisdiction_code
(
    sno integer, -- Serial row id in the master. Not officer-facing.
    state_jur_code character varying(50), -- JOIN KEY ↔ t_all_delers_api_v_t.stjd. Sample: "GJ041", "GJ018". State-jurisdiction code.
    division character varying(150), -- Division NAME — top-level officer jurisdiction. PROJECT this for "division". Sample: "Division 5 (VAD)", "Division 2 (ABD)".
    range character varying(150), -- Range NAME — mid-level officer jurisdiction (under division). PROJECT this for "range". Sample: "Range 10 (VAD)", "Range 5 (ABD)". (NOT the SQL keyword RANGE — qualify/quote when projecting.)
    unit character varying(150), -- Unit NAME — lowest-level officer jurisdiction (under range; aka "Ghatak"). PROJECT this for "unit"/"ghatak". In sql we can use unit ilike 'Ghatak 41 (%)'. Sample: "Ghatak 41 (VAD)", "Ghatak 18 (ABD)".
    record_status character varying(1), -- Row status. Sample: "A" (active).
    inserted_dt date, -- Date this jurisdiction row was inserted. Sample: "2023-09-23".
    db_remarks text, -- DB remarks if any (usually blank).
    h3 character varying(150), -- Optional duplicate of division. Sample: "Division 5 (VAD)".
    h2 character varying(150), -- Optional duplicate of range. Sample: "Range 10 (VAD)".
    h1 character varying(150), -- Optional duplicate of unit. Sample: "Ghatak 41 (VAD)".
    last_updated_dt timestamp without time zone, -- Last-updated timestamp.
    -- state_jur_code is 1-row-per-jurisdiction (unique). Mark UNIQUE so the 2-hop
    -- decode join (dealer.stjd = state_jur_code) is 1:N, not M:N — no false
    -- fan-out on COUNT/SUM. (UNIQUE, not PRIMARY KEY: live table declares no PK.)
    UNIQUE (state_jur_code)
)

-- Join hints:
-- common.t_all_delers_api_v_t.gstin can be joined with live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned.gstin
-- common.t_all_delers_api_v_t.stjd can be joined with common.mst_state_jurisdiction_code.state_jur_code