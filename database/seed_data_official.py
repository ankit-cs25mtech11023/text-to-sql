"""
Seed official GST schemas v2 (EWB, GSTR-3B normalized, GSTR-7, GSTREG, common masters)
with adversarial toy data in PostgreSQL.

v2 (Phase 8): flat GSTR-3B MV dropped -> normalized 17-table public.tbl_gst_rtn_r3b*;
NEW common.t_all_delers_api_v_t dealer master + common.mst_state_jurisdiction_code;
full-column common.mst_fy_years_t / mst_3bd_months_t.

Adversarial seed rules (distinguishability audit fix list, results/README.md W1):
 - distinct value magnitudes per identical-shape 3B section table (osupdet/osupzero/
   osupnilexmp/osupnongst/isuprev) -> table-swap mutator cannot collide
 - unequal event counts (canceldet=2, rejdtl=1, extenddet=3, transdet=4, tdsa=3)
 - partial cash payment (paid < payable) + one unpaid return
 - zero AND NULL reverse-charge rows -> filters/aggregates bite
 - duplicate deductee names across gstins; >=1 single-return deductee
 - distinct argmax per measure (top-by-assval != top-by-igstval != top-by-InvVal;
   deductor top-by-amt_ded != top-by-TDS)
 - distinct-count asymmetry (5 consignor gstins vs 6 consignee names)

Round 2 (Option B re-seed, reseed_design.md — breaks the 15 seed-fixable
distinguishability collisions from the v2 audit):
 - per-month activity factors, SUM-preserving per FY (month-scoped aggregates
   decouple; FY totals/rankings unchanged) + one seasonal taxpayer (RAJKOT)
 - per-profile section fractions (zero/nil/nongst/rv orderings decoupled from
   turnover order -> section table-swaps break on ranking golds)
 - RCM-free returns (absent isuprev rows AND a zero-txval row variant)
 - filing gap (SURAT skips 062025) + a registered dealer with zero returns
 - GSTR-7: varied per-return payables, partial + unpaid payments,
   D3 top-by-#deductee-gstins vs D2 top-by-#names vs D1 top-by-TDS,
   amendments argmax != TDS argmax (no D1 amendment)
 - GSTREG: casual dealer with rgtodt set / canc_dt NULL; RAJKOT canc_dt<>rgtodt
CGST=SGST equal split KEPT (domain law, class-1 equivalence — collides on real data too).

Run:  python database/seed_data_official.py
Env:  DATABASE_URL  (default: postgresql:///gst_official)
      Creates the database automatically if it does not exist.
Exits non-zero if any post-seed validity check fails.
"""
import os
import re
import sys
from datetime import date, datetime, timedelta
from dotenv import load_dotenv
import psycopg2
from psycopg2 import sql as psql
from psycopg2.extras import execute_values

load_dotenv()
DSN = os.getenv("DATABASE_URL", "postgresql:///gst_official")


# ─── helpers ──────────────────────────────────────────────────────────────────

def r2(x: float) -> float:
    return round(x, 2)


def ensure_db(dsn: str) -> None:
    m = re.search(r"/([^/?]+)(\?.*)?$", dsn)
    if not m:
        return
    dbname = m.group(1)
    base = dsn[: dsn.rfind("/" + dbname)] + "/postgres"
    try:
        conn = psycopg2.connect(base)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
        if not cur.fetchone():
            cur.execute(psql.SQL("CREATE DATABASE {}").format(psql.Identifier(dbname)))
            print(f"  Created database '{dbname}'")
        else:
            print(f"  Database '{dbname}' already exists")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"  Note: could not auto-create database ({e}). Run: createdb {dbname}")


# ─── DROP (v1 + v2 objects; idempotent re-seed) ──────────────────────────────

DROP_ORDER = """
-- v1 flat MV lives in live_reports — schema removed entirely in v2
DROP SCHEMA IF EXISTS live_reports CASCADE;
-- EWB
DROP TABLE IF EXISTS public.tbl_ewb_parta_ewb_itemlist CASCADE;
DROP TABLE IF EXISTS public.tbl_ewb_parta_ewb CASCADE;
DROP TABLE IF EXISTS public.tbl_ewb_parta CASCADE;
DROP TABLE IF EXISTS public.tbl_ewb_partb_ewb_partbdet CASCADE;
DROP TABLE IF EXISTS public.tbl_ewb_partb_ewb_canceldet CASCADE;
DROP TABLE IF EXISTS public.tbl_ewb_partb_ewb_extenddet CASCADE;
DROP TABLE IF EXISTS public.tbl_ewb_partb_ewb_rejdtl CASCADE;
DROP TABLE IF EXISTS public.tbl_ewb_partb_ewb_transdet CASCADE;
DROP TABLE IF EXISTS public.tbl_ewb_partb_ewb CASCADE;
DROP TABLE IF EXISTS public.tbl_ewb_partb CASCADE;
-- GSTR-3B normalized (details -> parents -> main)
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_inward_sup_isup_details CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_inward_sup CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_itc_elg_itc_avl CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_itc_elg_itc_inelg CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_itc_elg_itc_net CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_itc_elg_itc_rev CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_itc_elg CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_sup_details_isuprev CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_sup_details_osupdet CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_sup_details_osupnilexmp CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_sup_details_osupnongst CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_sup_details_osupzero CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_sup_details CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_tx_pmt_pd_cash CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_tx_pmt_pd_itc CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b_tx_pmt CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r3b CASCADE;
-- masters + gstreg
DROP TABLE IF EXISTS common.mst_3bd_months_t CASCADE;
DROP TABLE IF EXISTS common.mst_fy_years_t CASCADE;
DROP TABLE IF EXISTS common.t_all_delers_api_v_t CASCADE;
DROP TABLE IF EXISTS common.mst_state_jurisdiction_code CASCADE;
-- GSTR-7
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tds_inv CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tds CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tdsa_inv CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tdsa CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tax_pay CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tax_paid_pd_by_cash CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tax_paid CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7 CASCADE;
"""


# ─── DDL: EWB (unchanged vs v1 — received ewb.sql is comment-reformat only) ───

DDL_EWB = [
    """CREATE TABLE IF NOT EXISTS public.tbl_ewb_parta (
        idtbl_ewb_parta BIGINT PRIMARY KEY,
        statecode VARCHAR,
        statename VARCHAR,
        category VARCHAR,
        period TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_ewb_parta_ewb (
        idtbl_ewb_parta_ewb BIGINT PRIMARY KEY,
        ewbno VARCHAR UNIQUE,
        ewbdt VARCHAR,
        usertyp VARCHAR,
        usergstin VARCHAR,
        transtyp VARCHAR,
        suptype VARCHAR,
        ssuptyp VARCHAR,
        doctyp VARCHAR,
        docno VARCHAR,
        docdt VARCHAR,
        frgstin VARCHAR,
        frname VARCHAR,
        frplac VARCHAR,
        frpin VARCHAR,
        frstat VARCHAR,
        togstin VARCHAR,
        toname VARCHAR,
        toplac VARCHAR,
        topin VARCHAR,
        tostat VARCHAR,
        assval NUMERIC,
        cgstval NUMERIC,
        sgstval NUMERIC,
        igstval NUMERIC,
        cessval NUMERIC,
        cessnonadvolval NUMERIC,
        otherval NUMERIC,
        status VARCHAR,
        rejstatus VARCHAR,
        travdist VARCHAR,
        ssupdesc VARCHAR,
        "InvVal" NUMERIC,
        ewbvaliddt VARCHAR,
        vehtype VARCHAR,
        despfrstat VARCHAR,
        shiptostat VARCHAR,
        idtbl_ewb_parta BIGINT REFERENCES public.tbl_ewb_parta(idtbl_ewb_parta),
        fraddr TEXT,
        toaddr TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_ewb_parta_ewb_itemlist (
        idtbl_ewb_parta_ewb_itemlist BIGINT PRIMARY KEY,
        itemno VARCHAR,
        prodnam VARCHAR,
        hsncod VARCHAR,
        qty VARCHAR,
        "QtyUqc" VARCHAR,
        cgstrt NUMERIC,
        sgstrt NUMERIC,
        igstrt NUMERIC,
        cessrt NUMERIC,
        assamt NUMERIC,
        cessadvol NUMERIC,
        cessnonadvol NUMERIC,
        idtbl_ewb_parta_ewb BIGINT REFERENCES public.tbl_ewb_parta_ewb(idtbl_ewb_parta_ewb)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_ewb_partb (
        ididtbl_ewb_partb BIGINT PRIMARY KEY,
        statecode VARCHAR,
        statename VARCHAR,
        category VARCHAR,
        period TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_ewb_partb_ewb (
        idtbl_ewb_partb_ewb BIGINT PRIMARY KEY,
        ewb_no VARCHAR,
        fin_valid_dt VARCHAR,
        idtbl_ewb_partb BIGINT REFERENCES public.tbl_ewb_partb(ididtbl_ewb_partb)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_ewb_partb_ewb_partbdet (
        idtbl_ewb_partb_ewb_partbdet BIGINT PRIMARY KEY,
        vehno VARCHAR,
        frplace VARCHAR,
        reascd VARCHAR,
        trdocno VARCHAR,
        updid VARCHAR,
        upddt VARCHAR,
        transmode VARCHAR,
        trdocdt VARCHAR,
        idtbl_ewb_partb_ewb BIGINT REFERENCES public.tbl_ewb_partb_ewb(idtbl_ewb_partb_ewb),
        ewb_no VARCHAR,
        valid_till_dt TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_ewb_partb_ewb_canceldet (
        idtbl_ewb_partb_ewb_canceldet BIGINT PRIMARY KEY,
        ewb_no TEXT,
        canceldt TEXT,
        cancelreascd TEXT,
        cancelreasrem TEXT,
        cancelby TEXT,
        idtbl_ewb_partb_ewb BIGINT REFERENCES public.tbl_ewb_partb_ewb(idtbl_ewb_partb_ewb)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_ewb_partb_ewb_extenddet (
        idtbl_ewb_partb_ewb_extenddet BIGINT PRIMARY KEY,
        extdt VARCHAR,
        extreascd VARCHAR,
        extreasrem VARCHAR,
        extby VARCHAR,
        frplace VARCHAR,
        remdist VARCHAR,
        prev_validdt VARCHAR,
        frstat VARCHAR,
        idtbl_ewb_partb_ewb BIGINT REFERENCES public.tbl_ewb_partb_ewb(idtbl_ewb_partb_ewb),
        ewb_no TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_ewb_partb_ewb_rejdtl (
        idtbl_ewb_partb_ewb_rejdtl BIGINT PRIMARY KEY,
        ewb_no TEXT,
        rejgstin TEXT,
        rejdt TEXT,
        idtbl_ewb_partb_ewb BIGINT REFERENCES public.tbl_ewb_partb_ewb(idtbl_ewb_partb_ewb)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_ewb_partb_ewb_transdet (
        idtbl_ewb_partb_ewb_transdet BIGINT PRIMARY KEY,
        transid VARCHAR,
        updid VARCHAR,
        upddt VARCHAR,
        idtbl_ewb_partb_ewb BIGINT REFERENCES public.tbl_ewb_partb_ewb(idtbl_ewb_partb_ewb),
        ewb_no TEXT
    )""",
]

# ─── DDL: GSTR-3B normalized, 17 tables (executable mirror of gstr3b.sql) ────
# Received DDL is READ-ONLY and has trailing commas -> not executable verbatim.
# Structure mirrored exactly: names, columns, types, FK chain (details -> parent -> main).

DDL_GSTR3B = [
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b (
        idtbl_gst_rtn_r3b BIGINT PRIMARY KEY,
        gstin VARCHAR,
        ret_period VARCHAR,
        fil_dt VARCHAR,
        process_date VARCHAR,
        process_no VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_inward_sup (
        idtbl_gst_rtn_r3b_inward_sup BIGINT PRIMARY KEY,
        idtbl_gst_rtn_r3b BIGINT REFERENCES public.tbl_gst_rtn_r3b(idtbl_gst_rtn_r3b)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_inward_sup_isup_details (
        idtbl_gst_rtn_r3b_inward_sup_isup_details BIGINT PRIMARY KEY,
        ty TEXT,
        inter NUMERIC,
        intra NUMERIC,
        idtbl_gst_rtn_r3b_inward_sup BIGINT
            REFERENCES public.tbl_gst_rtn_r3b_inward_sup(idtbl_gst_rtn_r3b_inward_sup)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_itc_elg (
        idtbl_gst_rtn_r3b_itc_elg BIGINT PRIMARY KEY,
        idtbl_gst_rtn_r3b BIGINT REFERENCES public.tbl_gst_rtn_r3b(idtbl_gst_rtn_r3b)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_itc_elg_itc_avl (
        idtbl_gst_rtn_r3b_itc_elg_itc_avl BIGINT PRIMARY KEY,
        ty TEXT,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        csamt NUMERIC,
        idtbl_gst_rtn_r3b_itc_elg BIGINT
            REFERENCES public.tbl_gst_rtn_r3b_itc_elg(idtbl_gst_rtn_r3b_itc_elg)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_itc_elg_itc_inelg (
        idtbl_gst_rtn_r3b_itc_elg_itc_inelg BIGINT PRIMARY KEY,
        ty TEXT,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        csamt NUMERIC,
        idtbl_gst_rtn_r3b_itc_elg BIGINT
            REFERENCES public.tbl_gst_rtn_r3b_itc_elg(idtbl_gst_rtn_r3b_itc_elg)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_itc_elg_itc_net (
        idtbl_gst_rtn_r3b_itc_elg_itc_net BIGINT PRIMARY KEY,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        csamt NUMERIC,
        idtbl_gst_rtn_r3b_itc_elg BIGINT
            REFERENCES public.tbl_gst_rtn_r3b_itc_elg(idtbl_gst_rtn_r3b_itc_elg)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_itc_elg_itc_rev (
        idtbl_gst_rtn_r3b_itc_elg_itc_rev BIGINT PRIMARY KEY,
        ty TEXT,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        csamt NUMERIC,
        idtbl_gst_rtn_r3b_itc_elg BIGINT
            REFERENCES public.tbl_gst_rtn_r3b_itc_elg(idtbl_gst_rtn_r3b_itc_elg)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_sup_details (
        idtbl_gst_rtn_r3b_sup_details BIGINT PRIMARY KEY,
        idtbl_gst_rtn_r3b BIGINT REFERENCES public.tbl_gst_rtn_r3b(idtbl_gst_rtn_r3b)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_sup_details_isuprev (
        idtbl_gst_rtn_r3b_sup_details_isuprev BIGINT PRIMARY KEY,
        txval NUMERIC,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        csamt NUMERIC,
        idtbl_gst_rtn_r3b_sup_details BIGINT
            REFERENCES public.tbl_gst_rtn_r3b_sup_details(idtbl_gst_rtn_r3b_sup_details)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_sup_details_osupdet (
        idtbl_gst_rtn_r3b_sup_details_osupdet BIGINT PRIMARY KEY,
        txval NUMERIC,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        csamt NUMERIC,
        idtbl_gst_rtn_r3b_sup_details BIGINT
            REFERENCES public.tbl_gst_rtn_r3b_sup_details(idtbl_gst_rtn_r3b_sup_details)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_sup_details_osupnilexmp (
        idtbl_gst_rtn_r3b_sup_details_osupnilexmp BIGINT PRIMARY KEY,
        txval NUMERIC,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        csamt NUMERIC,
        idtbl_gst_rtn_r3b_sup_details BIGINT
            REFERENCES public.tbl_gst_rtn_r3b_sup_details(idtbl_gst_rtn_r3b_sup_details)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_sup_details_osupnongst (
        idtbl_gst_rtn_r3b_sup_details_osupnongst BIGINT PRIMARY KEY,
        txval NUMERIC,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        csamt NUMERIC,
        idtbl_gst_rtn_r3b_sup_details BIGINT
            REFERENCES public.tbl_gst_rtn_r3b_sup_details(idtbl_gst_rtn_r3b_sup_details)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_sup_details_osupzero (
        idtbl_gst_rtn_r3b_sup_details_osupzero BIGINT PRIMARY KEY,
        txval NUMERIC,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        csamt NUMERIC,
        idtbl_gst_rtn_r3b_sup_details BIGINT
            REFERENCES public.tbl_gst_rtn_r3b_sup_details(idtbl_gst_rtn_r3b_sup_details)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_tx_pmt (
        idtbl_gst_rtn_r3b_tx_pmt BIGINT PRIMARY KEY,
        idtbl_gst_rtn_r3b BIGINT REFERENCES public.tbl_gst_rtn_r3b(idtbl_gst_rtn_r3b)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_tx_pmt_pd_cash (
        idtbl_gst_rtn_r3b_tx_pmt_pd_cash BIGINT PRIMARY KEY,
        liab_ldg_id TEXT,
        trans_typ TEXT,
        ipd NUMERIC,
        cpd NUMERIC,
        spd NUMERIC,
        cspd NUMERIC,
        i_intrpd NUMERIC,
        c_intrpd NUMERIC,
        s_intrpd NUMERIC,
        cs_intrpd NUMERIC,
        i_lfeepd NUMERIC,
        c_lfeepd NUMERIC,
        s_lfeepd NUMERIC,
        cs_lfeepd NUMERIC,
        idtbl_gst_rtn_r3b_tx_pmt BIGINT
            REFERENCES public.tbl_gst_rtn_r3b_tx_pmt(idtbl_gst_rtn_r3b_tx_pmt)
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r3b_tx_pmt_pd_itc (
        idtbl_gst_rtn_r3b_tx_pmt_pd_itc BIGINT PRIMARY KEY,
        liab_ldg_id TEXT,
        trans_typ TEXT,
        i_pdi NUMERIC,
        i_pdc NUMERIC,
        i_pds NUMERIC,
        c_pdi NUMERIC,
        c_pdc NUMERIC,
        s_pdi NUMERIC,
        s_pds NUMERIC,
        cs_pdcs NUMERIC,
        idtbl_gst_rtn_r3b_tx_pmt BIGINT
            REFERENCES public.tbl_gst_rtn_r3b_tx_pmt(idtbl_gst_rtn_r3b_tx_pmt)
    )""",
]


# ─── DDL: GSTREG (executable mirror of gstreg.sql — semicolons added) ─────────

DDL_GSTREG = [
    """CREATE TABLE IF NOT EXISTS common.t_all_delers_api_v_t (
        gstin CHARACTER VARYING(30),
        pan_num TEXT,
        lgnmbzpan CHARACTER VARYING,
        trdnm CHARACTER VARYING,
        stcd CHARACTER VARYING,
        appr_auth CHARACTER VARYING(20),
        stjd CHARACTER VARYING,
        ctjd CHARACTER VARYING,
        rgfmdt DATE,
        apprvdt DATE,
        apprv_mnth TEXT,
        rgtodt DATE,
        canc_dt DATE,
        canc_mnth TEXT,
        authstatus CHARACTER VARYING,
        type TEXT,
        ismigrated CHARACTER VARYING(20),
        regtypecd CHARACTER VARYING,
        isopcmp CHARACTER VARYING,
        iscasdl CHARACTER VARYING,
        cobz CHARACTER VARYING,
        psnt CHARACTER VARYING,
        ntcrbs TEXT,
        otherntbz TEXT,
        address TEXT,
        email CHARACTER VARYING,
        mobile CHARACTER VARYING,
        inserted_date DATE,
        regtype CHARACTER VARYING,
        can_arn TEXT,
        can_reasons TEXT,
        can_type TEXT,
        optcat TEXT,
        risk_profile TEXT,
        UNIQUE (gstin)
    )""",
    """CREATE TABLE IF NOT EXISTS common.mst_state_jurisdiction_code (
        sno INTEGER,
        state_jur_code CHARACTER VARYING(50),
        division CHARACTER VARYING(150),
        "range" CHARACTER VARYING(150),
        unit CHARACTER VARYING(150),
        record_status CHARACTER VARYING(1),
        inserted_dt DATE,
        db_remarks TEXT,
        h3 CHARACTER VARYING(150),
        h2 CHARACTER VARYING(150),
        h1 CHARACTER VARYING(150),
        last_updated_dt TIMESTAMP WITHOUT TIME ZONE,
        UNIQUE (state_jur_code)
    )""",
]


# ─── DDL: common masters, full columns (executable mirror of common_masters.sql)

DDL_MASTERS = [
    """CREATE TABLE IF NOT EXISTS common.mst_fy_years_t (
        flag_fy INTEGER,
        desc_year CHARACTER VARYING(10),
        desc_year_full CHARACTER VARYING(15),
        desc_year_fl_sql CHARACTER VARYING(15),
        fp_desc CHARACTER VARYING(10),
        record_status CHARACTER VARYING(5),
        fy_year_desc CHARACTER VARYING,
        UNIQUE (flag_fy)
    )""",
    """CREATE TABLE IF NOT EXISTS common.mst_3bd_months_t (
        mnth_id INTEGER,
        ret_period INTEGER,
        from_date DATE,
        to_date TIMESTAMP WITHOUT TIME ZONE,
        ct INTEGER,
        fy_year CHARACTER VARYING(20),
        fy_flag INTEGER,
        record_status CHARACTER VARYING(1),
        ret_period_fl CHARACTER VARYING(10),
        month_desc CHARACTER VARYING,
        mnth_cd INTEGER,
        quarter CHARACTER VARYING,
        quarter_all_mnths CHARACTER VARYING,
        UNIQUE (ret_period_fl),
        UNIQUE (mnth_id)
    )""",
]


# ─── DDL: GSTR-7 (unchanged vs v1 — received gstr7.sql is comment-reformat only)

DDL_GSTR7 = [
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r7 (
        idtbl_gst_rtn_r7 BIGINT PRIMARY KEY,
        fp VARCHAR,
        gstin VARCHAR,
        fil_dt VARCHAR,
        inserted_date TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r7_tds (
        idtbl_gst_rtn_r7_tds BIGINT PRIMARY KEY,
        gstin_ded TEXT,
        amt_ded NUMERIC,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        chksum TEXT,
        tbl_gst_rtn_r7 BIGINT REFERENCES public.tbl_gst_rtn_r7(idtbl_gst_rtn_r7),
        inserted_date TIMESTAMPTZ,
        deductee_name TEXT,
        idt TEXT,
        inum TEXT,
        ival TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r7_tds_inv (
        idtbl_gst_rtn_r7_tds_inv BIGINT PRIMARY KEY,
        inum TEXT,
        idt TEXT,
        ival NUMERIC,
        amt_ded NUMERIC,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        flag TEXT,
        chksum TEXT,
        idtbl_gst_rtn_r7_tds BIGINT REFERENCES public.tbl_gst_rtn_r7_tds(idtbl_gst_rtn_r7_tds),
        inserted_date TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r7_tdsa (
        idtbl_gst_rtn_r7_tdsa BIGINT PRIMARY KEY,
        ogstin_ded TEXT,
        omonth TEXT,
        oamt_ded NUMERIC,
        gstin_ded TEXT,
        amt_ded NUMERIC,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        chksum TEXT,
        source TEXT,
        act_tkn TEXT,
        tbl_gst_rtn_r7 BIGINT REFERENCES public.tbl_gst_rtn_r7(idtbl_gst_rtn_r7),
        inserted_date TIMESTAMPTZ,
        deductee_name TEXT,
        idt TEXT,
        inum TEXT,
        ival TEXT,
        odeductee_name TEXT,
        oidt TEXT,
        oinum TEXT,
        oival TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r7_tdsa_inv (
        idtbl_gst_rtn_r7_tdsa_inv BIGINT PRIMARY KEY,
        ogstin_ded TEXT,
        omonth TEXT,
        oamt_ded NUMERIC,
        gstin_ded TEXT,
        amt_ded NUMERIC,
        iamt NUMERIC,
        camt NUMERIC,
        samt NUMERIC,
        chksum TEXT,
        source TEXT,
        act_tkn TEXT,
        oinum TEXT,
        oidt TEXT,
        oival TEXT,
        inum TEXT,
        idt TEXT,
        ival TEXT,
        idtbl_gst_rtn_r7_tdsa BIGINT REFERENCES public.tbl_gst_rtn_r7_tdsa(idtbl_gst_rtn_r7_tdsa),
        inserted_date TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r7_tax_pay (
        idtbl_gst_rtn_r7_tax_pay BIGINT PRIMARY KEY,
        liab_id TEXT,
        trancd TEXT,
        trandate TEXT,
        igst_tx NUMERIC, igst_intr NUMERIC, igst_pen NUMERIC, igst_fee NUMERIC, igst_oth NUMERIC,
        cgst_tx NUMERIC, cgst_intr NUMERIC, cgst_pen NUMERIC, cgst_fee NUMERIC, cgst_oth NUMERIC,
        sgst_tx NUMERIC, sgst_intr NUMERIC, sgst_pen NUMERIC, sgst_fee NUMERIC, sgst_oth NUMERIC,
        cess_tx NUMERIC, cess_intr NUMERIC, cess_pen NUMERIC, cess_fee NUMERIC, cess_oth NUMERIC,
        tbl_gst_rtn_r7 BIGINT REFERENCES public.tbl_gst_rtn_r7(idtbl_gst_rtn_r7),
        inserted_date TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r7_tax_paid (
        idtbl_gst_rtn_r7_tax_paid BIGINT PRIMARY KEY,
        tbl_gst_rtn_r7 BIGINT REFERENCES public.tbl_gst_rtn_r7(idtbl_gst_rtn_r7),
        inserted_date TIMESTAMPTZ
    )""",
    """CREATE TABLE IF NOT EXISTS public.tbl_gst_rtn_r7_tax_paid_pd_by_cash (
        idtbl_gst_rtn_r7_tax_paid_pd_by_cash BIGINT PRIMARY KEY,
        liab_id TEXT,
        debit_id TEXT,
        trancd TEXT,
        trandate TEXT,
        igst_tx NUMERIC, igst_intr NUMERIC, igst_pen NUMERIC, igst_fee NUMERIC, igst_oth NUMERIC,
        cgst_tx NUMERIC, cgst_intr NUMERIC, cgst_pen NUMERIC, cgst_fee NUMERIC, cgst_oth NUMERIC,
        sgst_tx NUMERIC, sgst_intr NUMERIC, sgst_pen NUMERIC, sgst_fee NUMERIC, sgst_oth NUMERIC,
        cess_tx NUMERIC, cess_intr NUMERIC, cess_pen NUMERIC, cess_fee NUMERIC, cess_oth NUMERIC,
        idtbl_gst_rtn_r7_tax_paid BIGINT REFERENCES public.tbl_gst_rtn_r7_tax_paid(idtbl_gst_rtn_r7_tax_paid),
        inserted_date TIMESTAMPTZ
    )""",
]

# ─── shared metadata: taxpayer profiles + return periods ─────────────────────
# One profile per GSTIN — drives BOTH gstreg (dealer master) and GSTR-3B facts,
# so the r3b.gstin -> t_all_delers_api_v_t.gstin decode join always resolves.
# Adversarial levers baked in: distinct base turnover magnitudes, distinct
# igst_frac (top-by-IGST != top-by-turnover), distinct pur_frac (top-by-ITC a
# THIRD taxpayer), 2 cancelled taxpayers (canc_dt IS NOT NULL), asymmetric
# division membership (Div1=4 incl. never-filer, Div2=3, Div3=2).
# Re-seed round 2 (distinguishability fix, reseed_design.md): per-profile
# SECTION FRACTIONS (zero/nil/nongst/rv) whose orderings are decoupled from the
# base-turnover ordering -> section-table swaps break on ranking/argmax golds;
# rv=0 marks the always-RCM-free taxpayer.

R3B_PROFILES = [
    dict(gstin='24AAAAR0001A9AA', trdnm='SANGH TEXTILES LTD',
         lgnm='SANGH TEXTILES LIMITED AHMEDABAD', base=2_210_664, rate=0.09,
         igst_frac=0.00, pur_frac=0.50, auth='STATE', stjd='GJ011', ctjd='VC0101',
         division='Division 1 (ABD)', range='Range 1 (ABD)', unit='Ghatak 1 (ABD)',
         ntcrbs='Manufacturer', cobz='PVT', risk='LOW_RISK(1.00)', cancelled=False,
         zero=0.10, nil=0.12, nongst=0.015, rv=0.008),
    dict(gstin='24AAAAR0002B9AA', trdnm='PATEL CHEMICALS LTD',
         lgnm='PATEL CHEMICALS LIMITED', base=843_521, rate=0.09,
         igst_frac=0.30, pur_frac=0.55, auth='STATE', stjd='GJ012', ctjd='VC0102',
         division='Division 1 (ABD)', range='Range 1 (ABD)', unit='Ghatak 2 (ABD)',
         ntcrbs='Manufacturer', cobz='PVT', risk='MEDIUM_RISK(5.00)', cancelled=False,
         zero=0.28, nil=0.02, nongst=0.05, rv=0.030),
    dict(gstin='24AAAAR0003C9AA', trdnm='GUJARAT PHARMA CORP',
         lgnm='GUJARAT PHARMACEUTICAL CORPORATION', base=1_517_800, rate=0.06,
         igst_frac=0.10, pur_frac=0.95, auth='CENTER', stjd='GJ023', ctjd='VC0203',
         division='Division 1 (ABD)', range='Range 2 (ABD)', unit='Ghatak 3 (ABD)',
         ntcrbs='Manufacturer', cobz='PAR', risk='LOW_RISK(1.00)', cancelled=False,
         zero=0.22, nil=0.04, nongst=0.01, rv=0.015),
    dict(gstin='24AABCE0001D9AA', trdnm='SURAT TEXTILES PVT LTD',
         lgnm='SURAT TEXTILES PRIVATE LIMITED', base=1_234_567, rate=0.09,
         igst_frac=0.00, pur_frac=0.50, auth='STATE', stjd='GJ034', ctjd='VC0304',
         division='Division 2 (ABD)', range='Range 3 (ABD)', unit='Ghatak 4 (ABD)',
         ntcrbs='Trader', cobz='PRO', risk='NA', cancelled=False,
         zero=0.12, nil=0.025, nongst=0.04, rv=0.025,
         casual=True, rgtodt=date(2026, 3, 31)),
    dict(gstin='24AABCE0002E9AA', trdnm='AHMEDABAD STEEL WORKS',
         lgnm='AHMEDABAD STEEL WORKS LTD', base=3_061_234, rate=0.09,
         igst_frac=0.50, pur_frac=0.50, auth='STATE', stjd='GJ035', ctjd='VC0305',
         division='Division 2 (ABD)', range='Range 3 (ABD)', unit='Ghatak 5 (ABD)',
         ntcrbs='Manufacturer', cobz='PVT', risk='MEDIUM_RISK(5.00)', cancelled=False,
         zero=0.08, nil=0.03, nongst=0.02, rv=0.006),
    dict(gstin='24AABCE0003F9AA', trdnm='GUJARAT CEMENT LTD',
         lgnm='GUJARAT CEMENT LIMITED', base=2_498_765, rate=0.09,
         igst_frac=0.95, pur_frac=0.45, auth='CENTER', stjd='GJ046', ctjd='VC0406',
         division='Division 2 (ABD)', range='Range 4 (ABD)', unit='Ghatak 6 (ABD)',
         ntcrbs='Manufacturer', cobz='PVT', risk='LOW_RISK(1.00)', cancelled=False,
         zero=0.30, nil=0.05, nongst=0.012, rv=0.012),
    dict(gstin='24AACCD0001G9AA', trdnm='BARODA FOODS LTD',
         lgnm='BARODA FOODS LIMITED', base=511_111, rate=0.025,
         igst_frac=0.00, pur_frac=0.70, auth='STATE', stjd='GJ057', ctjd='VC0507',
         division='Division 3 (ABD)', range='Range 5 (ABD)', unit='Ghatak 7 (ABD)',
         ntcrbs='Trader', cobz='PRO', risk='NA', cancelled=True,
         zero=0.15, nil=0.11, nongst=0.06, rv=0.0,
         canc_dt=date(2025, 3, 31), rgtodt=date(2025, 3, 31), canc_mnth='032025'),
    dict(gstin='24AACCD0002H9AA', trdnm='RAJKOT AUTO PARTS',
         lgnm='RAJKOT AUTO PARTS PVT LTD', base=1_789_999, rate=0.14,
         igst_frac=0.40, pur_frac=1.10, auth='STATE', stjd='GJ058', ctjd='VC0508',
         division='Division 3 (ABD)', range='Range 5 (ABD)', unit='Ghatak 8 (ABD)',
         ntcrbs='Service Provider', cobz='PAR', risk='MEDIUM_RISK(5.00)', cancelled=True,
         zero=0.18, nil=0.06, nongst=0.03, rv=0.020,
         canc_dt=date(2024, 12, 15), rgtodt=date(2024, 11, 30), canc_mnth='122024'),
]

# Registered dealer with ZERO filed returns (any module) -> COUNT(dealers) can
# never collide with COUNT(DISTINCT filers). Div1 membership keeps division
# rollups asymmetric (4/3/2).
NONFILER_DEALERS = [
    dict(gstin='24AADDF0001Z9AA', trdnm='MEHSANA AGRO TRADERS',
         lgnm='MEHSANA AGRO TRADERS PROPRIETORSHIP', auth='STATE',
         stjd='GJ013', ctjd='VC0103',
         division='Division 1 (ABD)', range='Range 1 (ABD)', unit='Ghatak 9 (MSA)',
         ntcrbs='Trader', cobz='PRO', risk='NA', cancelled=False,
         rgfmdt=date(2025, 6, 1), apprvdt=date(2025, 6, 4), apprv_mnth='062025'),
]

# Per-month activity factors (multiply every supply-section value; ITC side
# stays monthly-constant). SUM per FY is EXACTLY the month count (6.00 / 3.00)
# -> all FY-total golds, rankings, and argmaxes are unchanged; only month-
# scoped aggregates decouple (audit themes #63/#77). RAJKOT gets a seasonal
# override (Jun+Sep light) so quarter-end subsets rank differently from FY.
R3B_MONTH_FACTORS = {
    '042024': 0.85, '052024': 1.05, '062024': 1.20,
    '072024': 0.90, '082024': 1.25, '092024': 0.75,
    '042025': 0.80, '052025': 1.10, '062025': 1.10,
}
R3B_SEASONAL_FACTORS = {
    '24AACCD0002H9AA': {                      # RAJKOT AUTO PARTS, FY8 override
        '042024': 1.60, '052024': 1.40, '062024': 0.50,
        '072024': 1.30, '082024': 0.80, '092024': 0.40,
    },
}

# Filing gaps: (gstin, ret_period) pairs NOT filed (non-filer months exist in
# reality; breaks uniform-count coincidences #53/#59).
R3B_SKIPPED_FILINGS = {('24AABCE0001D9AA', '062025')}          # SURAT skips Jun-2025

# RCM-free returns (audit theme #66): BARODA always (rv=0, row absent) +
# SANGH's FY9 returns (row absent) + PHARMA Apr/May-2024 (row present, txval 0).
RCM_ABSENT = {('24AAAAR0001A9AA', rp) for rp in ('042025', '052025', '062025')}
RCM_ZERO_ROW = {('24AAAAR0003C9AA', '042024'), ('24AAAAR0003C9AA', '052024')}

# Return period (MMYYYY) -> (mnth_id, fy_flag, month_name, mnth_cd, quarter, quarter_all)
# fy_flag 8 = FY2024-25, 9 = FY2025-26. `quarter` populated only on closing month.
R3B_PERIOD_META = {
    '042024': (82, 8, 'April',     4, '',   '062024'),
    '052024': (83, 8, 'May',       5, '',   '062024'),
    '062024': (84, 8, 'June',      6, 'Q1', '062024'),
    '072024': (85, 8, 'July',      7, '',   '092024'),
    '082024': (86, 8, 'August',    8, '',   '092024'),
    '092024': (87, 8, 'September', 9, 'Q2', '092024'),
    '042025': (94, 9, 'April',     4, '',   '062025'),
    '052025': (95, 9, 'May',       5, '',   '062025'),
    '062025': (96, 9, 'June',      6, 'Q1', '062025'),
}
R3B_FY8_PERIODS = ['042024', '052024', '062024', '072024', '082024', '092024']
R3B_FY9_PERIODS = ['042025', '052025', '062025']


def _month_end_ts(yyyy: int, mm: int) -> datetime:
    nxt = date(yyyy + (mm // 12), (mm % 12) + 1, 1)
    last = nxt - timedelta(days=1)
    return datetime(last.year, last.month, last.day, 23, 59, 0)


# ─── common masters (fy + month decode) ──────────────────────────────────────

def seed_masters(cur) -> None:
    fy_rows = []
    for flag in range(6, 11):                       # 6..10; facts use only 8, 9
        y1, y2 = 2016 + flag, 2017 + flag
        fy_rows.append((
            flag, f"{y1}-{str(y2)[2:]}", f"Apr {str(y1)[2:]}-Mar {str(y2)[2:]}",
            f"APR{str(y1)[2:]}-MAR{str(y2)[2:]}", f"03{y2}", 'A', f"{y1}-{y2}",
        ))
    execute_values(cur, """
        INSERT INTO common.mst_fy_years_t
          (flag_fy,desc_year,desc_year_full,desc_year_fl_sql,fp_desc,
           record_status,fy_year_desc)
        VALUES %s""", fy_rows)

    mon_rows = []
    for rp, (mnth_id, fy_flag, mname, mcd, qlabel, qall) in R3B_PERIOD_META.items():
        mm, yyyy = int(rp[:2]), int(rp[2:])
        fy_year = 'APR24-MAR25' if fy_flag == 8 else 'APR25-MAR26'
        mon_rows.append((
            mnth_id, int(rp), date(yyyy, mm, 1), _month_end_ts(yyyy, mm),
            mnth_id, fy_year, fy_flag, 'A', rp, mname, mcd, qlabel, qall,
        ))
    execute_values(cur, """
        INSERT INTO common.mst_3bd_months_t
          (mnth_id,ret_period,from_date,to_date,ct,fy_year,fy_flag,record_status,
           ret_period_fl,month_desc,mnth_cd,quarter,quarter_all_mnths)
        VALUES %s""", mon_rows)
    print("  masters: seeded")


# ─── GSTREG: jurisdiction master + dealer master ─────────────────────────────

def seed_gstreg(cur) -> None:
    all_dealers = R3B_PROFILES + NONFILER_DEALERS

    # jurisdiction decode (stjd -> division/range/unit); 1 row per dealer's stjd
    jur_rows = []
    for i, p in enumerate(all_dealers, start=1):
        jur_rows.append((
            i, p['stjd'], p['division'], p['range'], p['unit'], 'A',
            date(2023, 9, 23), '', p['division'], p['range'], p['unit'],
            datetime(2024, 1, 1, 0, 0, 0),
        ))
    execute_values(cur, """
        INSERT INTO common.mst_state_jurisdiction_code
          (sno,state_jur_code,division,"range",unit,record_status,inserted_dt,
           db_remarks,h3,h2,h1,last_updated_dt)
        VALUES %s""", jur_rows)

    # dealer master (1 row per GSTIN). rgtodt is NOT a cancellation proxy:
    # the casual dealer (SURAT) carries a registration-validity end date with
    # canc_dt NULL, and RAJKOT's rgtodt != canc_dt (audit themes #115/#124).
    dealer_rows = []
    for p in all_dealers:
        pan = p['gstin'][2:12]
        cx = p['cancelled']
        dealer_rows.append((
            p['gstin'], pan, p['lgnm'], p['trdnm'], p['gstin'][:2], p['auth'],
            p['stjd'], p['ctjd'],
            p.get('rgfmdt', date(2017, 7, 1)), p.get('apprvdt', date(2017, 7, 5)),
            p.get('apprv_mnth', '072017'),
            p.get('rgtodt'),                            # rgtodt
            p.get('canc_dt'),                           # canc_dt
            p.get('canc_mnth'),                         # canc_mnth
            'SC' if cx else 'A', 'S2S', 'Y', 'TP', 'R',
            'Y' if p.get('casual') else 'N', p['cobz'], 'OWN',
            p['ntcrbs'], '', f"{p['unit']} Industrial Area, Gujarat",
            f"{p['trdnm'].split()[0].lower()}@example.com", '9988' + p['gstin'][2:8],
            date(2023, 1, 1), 'R',
            ('AA' + p['gstin'][2:9]) if cx else None,   # can_arn
            'Business discontinued' if cx else None,    # can_reasons
            'Voluntary Cancellation' if cx else None,   # can_type
            None, p['risk'],
        ))
    execute_values(cur, """
        INSERT INTO common.t_all_delers_api_v_t
          (gstin,pan_num,lgnmbzpan,trdnm,stcd,appr_auth,stjd,ctjd,rgfmdt,apprvdt,
           apprv_mnth,rgtodt,canc_dt,canc_mnth,authstatus,type,ismigrated,regtypecd,
           isopcmp,iscasdl,cobz,psnt,ntcrbs,otherntbz,address,email,mobile,
           inserted_date,regtype,can_arn,can_reasons,can_type,optcat,risk_profile)
        VALUES %s""", dealer_rows)
    print("  gstreg: seeded")


# ─── EWB seed data (v1 data + adversarial event-count/argmax tweaks) ─────────

def seed_ewb(cur) -> None:
    parta_batches = [
        (1, '6',  'HARYANA',     'PARTA', ''),
        (2, '3',  'PUNJAB',      'PARTA', ''),
        (3, '24', 'GUJARAT',     'PARTA', ''),
        (4, '27', 'MAHARASHTRA', 'PARTA', ''),
        (5, '8',  'RAJASTHAN',   'PARTA', ''),
    ]
    execute_values(cur, "INSERT INTO public.tbl_ewb_parta VALUES %s", parta_batches)

    # 5 consignor GSTINs (C1-C5) vs 6 consignee NAMES (B1-B6) -> distinct-count asymmetry
    C1 = ('06AAECM0001F1ZK', 'Manikaran Power Limited',    'Panchkula', '134109', '6')
    C2 = ('03AACCN0001H1ZW', 'Punjab Agro Industries Ltd', 'Ludhiana',  '141001', '3')
    C3 = ('24AAAAR0001A9AA', 'Gujarat Textiles Ltd',       'Ahmedabad', '380001', '24')
    C4 = ('27AABCP0001K1ZM', 'Maharashtra Chemicals Pvt',  'Pune',      '411001', '27')
    C5 = ('08AABCR0001G1Z1', 'Rajasthan Cement Works',     'Jodhpur',   '342001', '8')
    B1 = ('03AACCN0002H1ZW', 'NabhaPower Limited PPL',     'Patiala',   '140401', '3')
    B2 = ('06AAECM0002F1ZK', 'Haryana Textiles Ltd',       'Faridabad', '121001', '6')
    B3 = ('24AAAAR0002A9AA', 'Gujarat Pharma Ltd',         'Surat',     '395001', '24')
    B4 = ('27AABCP0002K1ZM', 'Mumbai Trading Co',          'Mumbai',    '400001', '27')
    B5 = ('08AABCR0002G1Z1', 'Rajasthan Retail Corp',      'Jaipur',    '302001', '8')
    B6 = ('08AABCR0003K1Z9', 'Bikaner Distributors',       'Bikaner',   '334001', '8')

    def ewb_row(eid, ewbno, fr, to, assval, cgst, sgst, igst, status, dist, batch_id, day):
        inv_val = r2(assval + cgst + sgst + igst)
        dt = f"{day:02d}/04/2026 10:30:00 AM"
        valid = f"{min(day + 3, 30):02d}/04/2026 11:59:59 PM"
        return (
            eid, ewbno, dt, 'T', fr[0], '1', 'O', '1  ', 'INV',
            f"INV-2627-{eid:03d}", f"{day:02d}/04/2026",
            fr[0], fr[1], fr[2], fr[3], fr[4],
            to[0], to[1], to[2], to[3], to[4],
            assval, cgst, sgst, igst, 0, 0, 0,
            status, '', str(dist), '',
            inv_val, valid, 'R', fr[4], to[4], batch_id,
            f"{fr[2]} Industrial Area", f"{to[2]} Warehouse",
        )

    # Distinct argmax: top-assval=EWB13 (420000), top-igstval=EWB14 (68400),
    # top-InvVal=EWB3 (471500) -> three different bills.
    # Origin-state bill counts all DISTINCT (24:6, 6:5, 3:4, 8:3, 27:2) --
    # 'most bills by origin state' needs a unique answer (bill 10 rides C3).
    ewbs = [
        ewb_row( 1, '392234140001', C1, B1, 208700.78,     0,     0, 37566.14, 'ACT', 150, 1,  5),
        ewb_row( 2, '392234140002', C1, B4, 150000.00,     0,     0, 18000.00, 'ACT',1200, 1,  6),
        ewb_row( 3, '392234140003', C1, B3, 410000.00,     0,     0, 61500.00, 'ACT', 900, 1,  7),
        ewb_row( 4, '392234140004', C1, B1,  84000.00,     0,     0,  4200.00, 'ACT', 150, 1,  8),
        ewb_row( 5, '392234140005', C1, B5,  95000.00,     0,     0, 17100.00, 'ACT', 600, 1,  9),
        ewb_row( 6, '392234140006', C2, B1, 175000.00, 15750, 15750,     0,    'ACT',  80, 2, 10),
        ewb_row( 7, '392234140007', C2, B1,  62000.00,  3720,  3720,     0,    'ACT',  60, 2, 11),
        ewb_row( 8, '392234140008', C2, B2, 280000.00,     0,     0, 50400.00, 'ACT', 200, 2, 12),
        ewb_row( 9, '392234140009', C2, B2,  45000.00,     0,     0, 12600.00, 'ACT', 200, 2, 13),
        ewb_row(10, '392234140010', C3, B4, 190000.00,     0,     0, 34200.00, 'ACT',1400, 3, 14),
        ewb_row(11, '392234140011', C3, B3, 130000.00,  7800,  7800,     0,    'CNL',  50, 3, 15),
        ewb_row(12, '392234140012', C3, B3, 245000.00, 22050, 22050,     0,    'CNL',  70, 3, 16),
        ewb_row(13, '392234140013', C3, B3, 420000.00, 10500, 10500,     0,    'ACT',  90, 3, 17),
        ewb_row(14, '392234140014', C3, B4, 380000.00,     0,     0, 68400.00, 'ACT', 500, 3, 18),
        ewb_row(15, '392234140015', C3, B5, 155000.00,     0,     0, 27900.00, 'ACT', 700, 3, 19),
        ewb_row(16, '392234140016', C4, B5, 290000.00,     0,     0, 52200.00, 'ACT', 800, 4, 20),
        ewb_row(17, '392234140017', C4, B6, 170000.00,     0,     0, 20400.00, 'ACT', 600, 4, 21),
        ewb_row(18, '392234140018', C5, B3, 310000.00,     0,     0, 55800.00, 'CNL', 700, 5, 22),
        ewb_row(19, '392234140019', C5, B4,  88000.00,     0,     0,  4400.00, 'CNL', 800, 5, 23),
        ewb_row(20, '392234140020', C5, B1, 200000.00,     0,     0, 36000.00, 'EXP',1100, 5, 24),
    ]
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_parta_ewb (
            idtbl_ewb_parta_ewb,ewbno,ewbdt,usertyp,usergstin,transtyp,suptype,ssuptyp,
            doctyp,docno,docdt,frgstin,frname,frplac,frpin,frstat,
            togstin,toname,toplac,topin,tostat,
            assval,cgstval,sgstval,igstval,cessval,cessnonadvolval,otherval,
            status,rejstatus,travdist,ssupdesc,"InvVal",
            ewbvaliddt,vehtype,despfrstat,shiptostat,idtbl_ewb_parta,fraddr,toaddr
        ) VALUES %s""", ewbs)

    items = [
        ( 1,'1','Wood Pellets',     '44013100','29.43','MTS', 0,   0,  18, 0,150000.00, 0, 0, 1),
        ( 2,'2','Cotton Fabric',    '5208',    '500',  'MTS', 0,   0,  18, 0, 58700.78, 0, 0, 1),
        ( 3,'1','Flat Rolled Steel','7208',    '12',   'MTS', 0,   0,  12, 0,150000.00, 0, 0, 2),
        ( 4,'1','Computers',        '8471',    '100',  'NOS', 0,   0,  18, 0,200000.00, 0, 0, 3),
        ( 5,'2','Pharma Products',  '3004',    '50',   'NOS', 0,   0,  18, 0,120000.00, 0, 0, 3),
        ( 6,'1','T-Shirts',         '6109',    '2000', 'NOS', 0,   0,   5, 0, 84000.00, 0, 0, 4),
        ( 7,'1','Wood Pellets',     '44013100','15',   'MTS', 0,   0,  18, 0, 95000.00, 0, 0, 5),
        ( 8,'1','Cotton Fabric',    '5208',    '300',  'MTS', 9,   9,   0, 0,100000.00, 0, 0, 6),
        ( 9,'2','Cotton Fabric',    '5208',    '150',  'MTS', 9,   9,   0, 0, 75000.00, 0, 0, 6),
        (10,'1','Pharma Products',  '3004',    '200',  'NOS', 6,   6,   0, 0, 62000.00, 0, 0, 7),
        (11,'1','Flat Rolled Steel','7208',    '20',   'MTS', 0,   0,  18, 0,280000.00, 0, 0, 8),
        (12,'1','Agri Machinery',   '84321000','2',    'NOS', 0,   0,  28, 0, 45000.00, 0, 0, 9),
        (13,'1','Computers',        '8471',    '50',   'NOS', 0,   0,  18, 0,190000.00, 0, 0,10),
        (14,'1','Cotton Fabric',    '5208',    '200',  'MTS', 6,   6,   0, 0,130000.00, 0, 0,11),
        (15,'1','Computers',        '8471',    '30',   'NOS', 9,   9,   0, 0,245000.00, 0, 0,12),
        (16,'1','T-Shirts',         '6109',    '5000', 'NOS', 2.5, 2.5, 0, 0,420000.00, 0, 0,13),
        (17,'1','Flat Rolled Steel','7208',    '25',   'MTS', 0,   0,  18, 0,380000.00, 0, 0,14),
        (18,'1','Wood Pellets',     '44013100','20',   'MTS', 0,   0,  18, 0,155000.00, 0, 0,15),
        (19,'1','Pharma Products',  '3004',    '500',  'NOS', 0,   0,  18, 0,290000.00, 0, 0,16),
        (20,'1','Cotton Fabric',    '5208',    '400',  'MTS', 0,   0,  12, 0,170000.00, 0, 0,17),
        (21,'1','Wood Pellets',     '44013100','22',   'MTS', 0,   0,  18, 0,310000.00, 0, 0,18),
        (22,'1','T-Shirts',         '6109',    '3000', 'NOS', 0,   0,   5, 0, 88000.00, 0, 0,19),
        (23,'1','Computers',        '8471',    '40',   'NOS', 0,   0,  18, 0,200000.00, 0, 0,20),
    ]
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_parta_ewb_itemlist (
            idtbl_ewb_parta_ewb_itemlist,itemno,prodnam,hsncod,qty,"QtyUqc",
            cgstrt,sgstrt,igstrt,cessrt,assamt,cessadvol,cessnonadvol,
            idtbl_ewb_parta_ewb
        ) VALUES %s""", items)

    partb_batches = [
        (1, '6',  'HARYANA', 'PARTB', ''),
        (2, '3',  'PUNJAB',  'PARTB', ''),
        (3, '24', 'GUJARAT', 'PARTB', ''),
    ]
    execute_values(cur, "INSERT INTO public.tbl_ewb_partb VALUES %s", partb_batches)

    partb_ewbs = []
    for i in range(1, 13):
        batch = 1 if i <= 5 else (2 if i <= 10 else 3)
        day = min(i + 4, 30)
        partb_ewbs.append((i, f"39223414{i:04d}", f"{day:02d}/04/2026 11:59:59 PM", batch))
    execute_values(cur, "INSERT INTO public.tbl_ewb_partb_ewb VALUES %s", partb_ewbs)

    vehicles = ['HR26AB1234','HR26CD5678','HR26EF9012','HR29GH3456','HR29IJ7890',
                'PB10KB0326','PB10LC1234','PB65MD5678','PB07NE9012','PB10OF3456',
                'GJ27TG8978','GJ01PH2345']
    trans_modes = ['1  ','1  ','1  ','1  ','2  ','1  ','1  ','1  ','1  ','1  ','1  ','3  ']
    partbdet_rows = []
    for i, (veh, mode) in enumerate(zip(vehicles, trans_modes), start=1):
        day = min(i + 4, 30)
        partbdet_rows.append((
            i, veh, 'HARYANA' if i <= 5 else ('PUNJAB' if i <= 10 else 'GUJARAT'),
            '', '', f"0{i}AAECS000{i}H1ZA", f"{day:02d}/04/2026 07:44:00 AM", mode,
            '', i, f"39223414{i:04d}", '',
        ))
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_partb_ewb_partbdet (
            idtbl_ewb_partb_ewb_partbdet,vehno,frplace,reascd,trdocno,updid,upddt,
            transmode,trdocdt,idtbl_ewb_partb_ewb,ewb_no,valid_till_dt
        ) VALUES %s""", partbdet_rows)

    # canceldet = 2  (EWBs 11, 12 -> CNL)
    cancel_rows = [
        (1, '392234140011', '15/04/2026 09:00:00 AM', '3', 'Duplicate EWB', '24AAAAR0003C9AA', 11),
        (2, '392234140012', '16/04/2026 11:30:00 AM', '4', 'Wrong entry',   '24AAAAR0003C9AA', 12),
    ]
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_partb_ewb_canceldet (
            idtbl_ewb_partb_ewb_canceldet,ewb_no,canceldt,cancelreascd,
            cancelreasrem,cancelby,idtbl_ewb_partb_ewb
        ) VALUES %s""", cancel_rows)

    # extenddet = 3  (EWBs 3, 5, 7)
    extend_rows = [
        (1,'09/04/2026 08:00:00 PM','4', 'Delay in transit', 'driver001', 'Ambala',  '80', '07/04/2026 11:59:59 PM','6',3,'392234140003'),
        (2,'11/04/2026 10:00:00 AM','4', 'Vehicle breakdown','transport2','Bhatinda','120','09/04/2026 11:59:59 PM','3',5,'392234140005'),
        (3,'13/04/2026 06:00:00 PM','99','Other reason',     'carrier3',  'Ludhiana','50', '11/04/2026 11:59:59 PM','3',7,'392234140007'),
    ]
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_partb_ewb_extenddet (
            idtbl_ewb_partb_ewb_extenddet,extdt,extreascd,extreasrem,extby,
            frplace,remdist,prev_validdt,frstat,idtbl_ewb_partb_ewb,ewb_no
        ) VALUES %s""", extend_rows)

    # rejdtl = 1  (EWB 8 only)
    rej_rows = [
        (1, '392234140008', '06AAECM0002F1ZK', '12/04/2026 01:19:49 PM', 8),
    ]
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_partb_ewb_rejdtl (
            idtbl_ewb_partb_ewb_rejdtl,ewb_no,rejgstin,rejdt,idtbl_ewb_partb_ewb
        ) VALUES %s""", rej_rows)

    # transdet = 4  (EWBs 1, 4, 6, 10)
    trans_rows = [
        (1,'88AAECS0001H1ZA','API_HARYANA     ','05/04/2026 01:42:00 PM', 1,'392234140001'),
        (2,'08AAICK0001B1ZE','API_PUNJAB      ','08/04/2026 09:15:00 AM', 4,'392234140004'),
        (3,'03AADFP0001Q1ZR','API_HARYANA     ','10/04/2026 11:00:00 AM', 6,'392234140006'),
        (4,'27AABCP0003K1ZM','API_PUNJAB      ','14/04/2026 08:30:00 AM',10,'392234140010'),
    ]
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_partb_ewb_transdet (
            idtbl_ewb_partb_ewb_transdet,transid,updid,upddt,
            idtbl_ewb_partb_ewb,ewb_no
        ) VALUES %s""", trans_rows)

    print("  EWB: seeded")


# ─── GSTR-3B normalized seed data (17 tables, FK-consistent) ─────────────────
# One return -> 1 main + 1 inward_sup(+2 details) + 1 itc_elg(+7 rows across
# avl/inelg/net/rev) + 1 sup_details(+5 section rows) + 1 tx_pmt(+cash/itc lines).
# Section tables (osupdet/osupzero/osupnilexmp/osupnongst/isuprev) share the
# (txval,iamt,camt,samt,csamt) shape -> each gets a DISTINCT magnitude ratio of
# the taxpayer's base turnover so the table-swap mutator cannot collide.

def seed_gstr3b(cur) -> None:
    rows = {k: [] for k in (
        'main','inw','isupd','itce','avl','inelg','net','rev','sd','isuprev',
        'osupdet','osupnil','osupnongst','osupzero','txp','cash','pditc')}
    ids = {k: 0 for k in rows}

    def nid(k):
        ids[k] += 1
        return ids[k]

    UNPAID = (5, '092024')      # GUJARAT CEMENT, Sep 2024 -> tx_pmt with NO cash/itc children
    INTEREST = (0, '042024')    # SANGH TEXTILES, Apr 2024 -> extra 30003 interest/late-fee cash line

    plan = [(i, p, rp) for i, p in enumerate(R3B_PROFILES) for rp in R3B_FY8_PERIODS]
    plan += [(i, p, rp) for i, p in enumerate(R3B_PROFILES[:5]) for rp in R3B_FY9_PERIODS]
    plan = [(i, p, rp) for i, p, rp in plan
            if (p['gstin'], rp) not in R3B_SKIPPED_FILINGS]

    for idx, p, rp in plan:
        rid = nid('main')
        mm, yyyy = int(rp[:2]), int(rp[2:])
        rows['main'].append((
            rid, p['gstin'], rp, f"20-{mm + 1:02d}-{yyyy}",
            f"{yyyy}-{mm + 1:02d}-20", str(20 + rid % 30)))

        T, r, f, pf = p['base'], p['rate'], p['igst_frac'], p['pur_frac']
        fm = R3B_SEASONAL_FACTORS.get(p['gstin'], {}).get(rp, R3B_MONTH_FACTORS[rp])
        Tm = T * fm                                     # month-scaled turnover
        intra, inter = r2(Tm * (1 - f)), r2(Tm * f)
        no_rcm = p['rv'] == 0 or (p['gstin'], rp) in RCM_ABSENT
        zero_rcm_row = (p['gstin'], rp) in RCM_ZERO_ROW

        # inward supplies (ty GST / NONGST)
        iw = nid('inw'); rows['inw'].append((iw, rid))
        rows['isupd'].append((nid('isupd'), 'GST',    r2(Tm * 0.04), r2(Tm * 0.08), iw))
        rows['isupd'].append((nid('isupd'), 'NONGST', r2(Tm * 0.01), r2(Tm * 0.02), iw))

        # supply details — per-profile section fractions, month-scaled
        sd = nid('sd'); rows['sd'].append((sd, rid))
        o_c = r2(intra * r); o_s = o_c; o_i = r2(inter * 2 * r)
        rows['osupdet'].append((nid('osupdet'), r2(Tm), o_i, o_c, o_s, 0, sd))
        z = r2(Tm * p['zero'])
        rows['osupzero'].append((nid('osupzero'), z, r2(z * 0.02), 0, 0, 0, sd))
        rows['osupnil'].append((nid('osupnil'), r2(Tm * p['nil']), 0, 0, 0, 0, sd))
        rows['osupnongst'].append((nid('osupnongst'), r2(Tm * p['nongst']), 0, 0, 0, 0, sd))
        if no_rcm:
            rv_c = 0.0                                  # no isuprev row at all
        elif zero_rcm_row:
            rv_c = 0.0
            rows['isuprev'].append((nid('isuprev'), 0, 0, 0, 0, 0, sd))
        else:
            rv = r2(Tm * p['rv']); rv_c = r2(rv * r)
            rows['isuprev'].append((nid('isuprev'), rv, 0, rv_c, rv_c, 0, sd))

        # ITC — distinct magnitude per table (monthly-constant, NOT month-scaled)
        itce = nid('itce'); rows['itce'].append((itce, rid))
        pur = r2(T * pf)
        avl_c = r2(pur * r * (1 - f)); avl_s = avl_c; avl_i = r2(pur * f * 2 * r)
        rows['avl'].append((nid('avl'), 'OTH',  avl_i, avl_c, avl_s, 0, itce))       # largest ITC
        if zero_rcm_row:
            rows['avl'].append((nid('avl'), 'ISRC', 0, 0, 0, 0, itce))
        elif not no_rcm:
            rows['avl'].append((nid('avl'), 'ISRC', 0, rv_c, rv_c, 0, itce))         # RCM credit (small)
        inelg_c = r2(T * 0.001 * r)
        rows['inelg'].append((nid('inelg'), 'RUL', 0, inelg_c, inelg_c, 0, itce))    # tiny
        rows['inelg'].append((nid('inelg'), 'OTH', 0, 0, 0, 0, itce))
        rev_c = r2(T * 0.003 * r)
        rows['rev'].append((nid('rev'), 'RUL', 0, rev_c, rev_c, 0, itce))            # tiny, != inelg
        rows['rev'].append((nid('rev'), 'OTH', 0, 0, 0, 0, itce))
        net_i = avl_i; net_c = r2(avl_c + rv_c - rev_c); net_s = net_c
        rows['net'].append((nid('net'), net_i, net_c, net_s, 0, itce))

        # tax payment
        txp = nid('txp'); rows['txp'].append((txp, rid))
        if (idx, rp) != UNPAID:
            use_i = r2(min(net_i, o_i)); use_c = r2(min(net_c, o_c)); use_s = r2(min(net_s, o_s))
            liab = f"{97597400 + txp}"
            rows['pditc'].append((nid('pditc'), liab, '30002',
                                  use_i, 0, 0, 0, use_c, 0, use_s, 0, txp))
            cash_i = r2(max(0, o_i - net_i)); cash_c = r2(max(0, o_c - net_c)); cash_s = r2(max(0, o_s - net_s))
            rows['cash'].append((nid('cash'), liab, '30002',
                                 cash_i, cash_c, cash_s, 0, 0, 0, 0, 0, 0, 0, 0, 0, txp))
            if (idx, rp) == INTEREST:
                # cs_intrpd deliberately NONZERO on this Div-1 line: ranking by
                # cs_intrpd must not tie back to the top-cash division (Div 2)
                rows['cash'].append((nid('cash'), liab, '30003',
                                     0, 0, 0, 0, 500.00, 300.00, 300.00, 50.00,
                                     200.00, 100.00, 100.00, 0, txp))

    # insert in FK dependency order (parents before children)
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b
        (idtbl_gst_rtn_r3b,gstin,ret_period,fil_dt,process_date,process_no)
        VALUES %s""", rows['main'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_inward_sup
        (idtbl_gst_rtn_r3b_inward_sup,idtbl_gst_rtn_r3b) VALUES %s""", rows['inw'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_inward_sup_isup_details
        (idtbl_gst_rtn_r3b_inward_sup_isup_details,ty,inter,intra,
         idtbl_gst_rtn_r3b_inward_sup) VALUES %s""", rows['isupd'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_itc_elg
        (idtbl_gst_rtn_r3b_itc_elg,idtbl_gst_rtn_r3b) VALUES %s""", rows['itce'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_itc_elg_itc_avl
        (idtbl_gst_rtn_r3b_itc_elg_itc_avl,ty,iamt,camt,samt,csamt,
         idtbl_gst_rtn_r3b_itc_elg) VALUES %s""", rows['avl'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_itc_elg_itc_inelg
        (idtbl_gst_rtn_r3b_itc_elg_itc_inelg,ty,iamt,camt,samt,csamt,
         idtbl_gst_rtn_r3b_itc_elg) VALUES %s""", rows['inelg'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_itc_elg_itc_net
        (idtbl_gst_rtn_r3b_itc_elg_itc_net,iamt,camt,samt,csamt,
         idtbl_gst_rtn_r3b_itc_elg) VALUES %s""", rows['net'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_itc_elg_itc_rev
        (idtbl_gst_rtn_r3b_itc_elg_itc_rev,ty,iamt,camt,samt,csamt,
         idtbl_gst_rtn_r3b_itc_elg) VALUES %s""", rows['rev'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_sup_details
        (idtbl_gst_rtn_r3b_sup_details,idtbl_gst_rtn_r3b) VALUES %s""", rows['sd'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_sup_details_isuprev
        (idtbl_gst_rtn_r3b_sup_details_isuprev,txval,iamt,camt,samt,csamt,
         idtbl_gst_rtn_r3b_sup_details) VALUES %s""", rows['isuprev'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_sup_details_osupdet
        (idtbl_gst_rtn_r3b_sup_details_osupdet,txval,iamt,camt,samt,csamt,
         idtbl_gst_rtn_r3b_sup_details) VALUES %s""", rows['osupdet'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_sup_details_osupnilexmp
        (idtbl_gst_rtn_r3b_sup_details_osupnilexmp,txval,iamt,camt,samt,csamt,
         idtbl_gst_rtn_r3b_sup_details) VALUES %s""", rows['osupnil'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_sup_details_osupnongst
        (idtbl_gst_rtn_r3b_sup_details_osupnongst,txval,iamt,camt,samt,csamt,
         idtbl_gst_rtn_r3b_sup_details) VALUES %s""", rows['osupnongst'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_sup_details_osupzero
        (idtbl_gst_rtn_r3b_sup_details_osupzero,txval,iamt,camt,samt,csamt,
         idtbl_gst_rtn_r3b_sup_details) VALUES %s""", rows['osupzero'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_tx_pmt
        (idtbl_gst_rtn_r3b_tx_pmt,idtbl_gst_rtn_r3b) VALUES %s""", rows['txp'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_tx_pmt_pd_cash
        (idtbl_gst_rtn_r3b_tx_pmt_pd_cash,liab_ldg_id,trans_typ,ipd,cpd,spd,cspd,
         i_intrpd,c_intrpd,s_intrpd,cs_intrpd,i_lfeepd,c_lfeepd,s_lfeepd,cs_lfeepd,
         idtbl_gst_rtn_r3b_tx_pmt) VALUES %s""", rows['cash'])
    execute_values(cur, """INSERT INTO public.tbl_gst_rtn_r3b_tx_pmt_pd_itc
        (idtbl_gst_rtn_r3b_tx_pmt_pd_itc,liab_ldg_id,trans_typ,i_pdi,i_pdc,i_pds,
         c_pdi,c_pdc,s_pdi,s_pds,cs_pdcs,idtbl_gst_rtn_r3b_tx_pmt) VALUES %s""", rows['pditc'])

    print(f"  GSTR-3B: seeded ({len(rows['main'])} returns)")


# ─── GSTR-7 seed data (v1 data + duplicate-name / solo-deductee / tdsa tweaks) ─

def seed_gstr7(cur) -> None:
    TS = '2025-10-14 12:12:23.991941+05:30'

    deductors = [
        ('03AABCP9999J2DM', 'Punjab Dept Public Works'),
        ('06AABCE0001M1ZP', 'Haryana Power Corporation'),
        ('27AABCP0001K1ZM', 'Maharashtra Water Authority'),
        ('24AAAAM0001J1ZP', 'Gujarat Infrastructure Corp'),
    ]
    periods = ['102025', '112025', '122025']

    r7_rows = []; r7_map = {}; r7_id = 1
    for gstin, _ in deductors:
        for fp in periods:
            day = 29 if fp == '102025' else 28
            fil = f"{day}-{fp[:2]}-{fp[2:]}"
            r7_rows.append((r7_id, fp, gstin, fil, TS))
            r7_map[(gstin, fp)] = r7_id
            r7_id += 1
    execute_values(cur, "INSERT INTO public.tbl_gst_rtn_r7 VALUES %s", r7_rows)

    tds_rows = []; tds_inv_rows = []; tds_id = 1; tds_inv_id = 1
    D = {'WB':'19AABCK9999C1ZI', 'PB':'03AADFP9999Q1ZR', 'MH':'27AAACC9999G1ZD',
         'HR':'06AAACK0000K1ZF', 'GJ':'24AAAAM0002J1ZS'}
    MH_DUP = '27AAACC8888G1ZD'     # different GSTIN, SAME deductee NAME as D['MH']
    SOLO   = '29AAAAS7777S1ZS'     # appears in exactly one return

    def tds_entry(r7_fk, ded_gstin, ded_name, amt, is_inter):
        nonlocal tds_id, tds_inv_id
        if is_inter:
            iamt, camt, samt = r2(amt * 0.02), 0, 0
        else:
            iamt, camt, samt = 0, r2(amt * 0.01), r2(amt * 0.01)
        tds_rows.append((tds_id, ded_gstin, amt, iamt, camt, samt,
                         None, r7_fk, TS, ded_name, None, None, None))
        inv_amt = r2(amt * 0.55)
        for k in range(1, 3):
            iv = r2(inv_amt * k * 1.18); ad = r2(inv_amt * k)
            i_i = r2(ad * 0.02) if is_inter else 0
            c_a = 0 if is_inter else r2(ad * 0.01)
            s_a = c_a
            tds_inv_rows.append((
                tds_inv_id, f"INV/{r7_fk:03d}/{k:02d}", f"2{k:02d}-10-2025",
                iv, ad, i_i, c_a, s_a, 'N', None, tds_id, TS))
            tds_inv_id += 1
        tds_id += 1

    # Argmax design (reseed_design.md F6): D1 = top by total TDS (197.2k/period
    # vs D3 190k); D3 = top by #distinct deductee GSTINs (5, incl. 2 dup-name
    # extras -> only 3 distinct names); D2 = top by #distinct deductee NAMES (4).
    # A camt->iamt swap (2*iamt+samt) flips the argmax to inter-heavy D3.
    GJ_DUP = '24AAAAM0003J1ZT'     # different GSTIN, SAME name as D['GJ'] row in D3
    PB_DUP = '27AADFP0001Q1ZC'     # different GSTIN, SAME name as D['PB'] row in D3
    NEW2   = '06AAHRC0001R1ZF'     # D2's 4th deductee, unique name
    AC_DUP = '24AAACA0001B1ZQ'     # D4's 3rd deductee, dup name -> 11 gstins vs 10 names

    for fp in periods:                                   # Deductor 1 -> top total TDS
        fk = r7_map[('03AABCP9999J2DM', fp)]
        tds_entry(fk, D['WB'], 'WB Contractors Ltd', 7_669_081, True)
        tds_entry(fk, D['PB'], 'Punjab IT Services', 2_191_166, False)
    for i, fp in enumerate(periods):                     # Deductor 2 -> most distinct NAMES (4)
        fk = r7_map[('06AABCE0001M1ZP', fp)]
        tds_entry(fk, D['MH'], 'MH Engineering Works',  5_000_000, True)
        tds_entry(fk, D['HR'], 'HR Civil Contractors',  1_000_000, False)
        tds_entry(fk, NEW2,    'Haryana Road Corp',       400_000, False)
        if i == 0:
            tds_entry(fk, SOLO, 'Solo Vendor Pvt Ltd',    333_333, False)
    for fp in periods:                                   # Deductor 3 -> most deductee GSTINs (5)
        fk = r7_map[('27AABCP0001K1ZM', fp)]
        tds_entry(fk, D['GJ'], 'GJ Supply Corp',       1_500_000, True)
        tds_entry(fk, GJ_DUP,  'GJ Supply Corp',       4_500_000, True)
        tds_entry(fk, D['PB'], 'Punjab Suppliers',     2_400_000, True)
        tds_entry(fk, D['MH'], 'MH Local Vendor',        500_000, False)
        tds_entry(fk, PB_DUP,  'Punjab Suppliers',       200_000, False)
    for fp in periods:                                   # Deductor 4 (duplicate NAME, diff GSTIN)
        # D['GJ'] is the top DEDUCTEE by TDS via this camt-heavy intra line
        # (+ its small D3 inter line) -> a camt/samt column-swap flips the
        # deductee argmax back to inter-only WB (audit #97)
        fk = r7_map[('24AAAAM0001J1ZP', fp)]
        tds_entry(fk, D['GJ'],  'Ahmedabad Constructions', 6_800_000, False)
        tds_entry(fk, MH_DUP,   'MH Engineering Works',     2_500_000, True)
        tds_entry(fk, AC_DUP,   'Ahmedabad Constructions',    250_000, False)

    execute_values(cur, """
        INSERT INTO public.tbl_gst_rtn_r7_tds (
            idtbl_gst_rtn_r7_tds,gstin_ded,amt_ded,iamt,camt,samt,
            chksum,tbl_gst_rtn_r7,inserted_date,deductee_name,idt,inum,ival
        ) VALUES %s""", tds_rows)
    execute_values(cur, """
        INSERT INTO public.tbl_gst_rtn_r7_tds_inv (
            idtbl_gst_rtn_r7_tds_inv,inum,idt,ival,amt_ded,iamt,camt,samt,
            flag,chksum,idtbl_gst_rtn_r7_tds,inserted_date
        ) VALUES %s""", tds_inv_rows)

    # tdsa = 3 amendments — deliberately NO amendment for D1 (top-TDS deductor):
    # ranking deductors via the tdsa table must NOT reproduce the tds argmax
    # (top by amendment TDS = D2, 110k), and the tdsa top DEDUCTEE must not
    # reproduce the tds top deductee D['GJ'] (top = D['MH']). D2 nov, D3 nov,
    # D4 oct.
    tdsa_rows = [
        (1, D['MH'],'112025',5_000_000, D['MH'],5_500_000,110_000.00,0,0,
         None,'C','Y', r7_map[('06AABCE0001M1ZP','122025')], TS,
         'MH Engineering Works',None,None,None,'MH Engineering Works',None,None,None),
        (2, D['GJ'],'112025',1_500_000, D['GJ'],1_550_000, 31_000.00,0,0,
         None,'C','Y', r7_map[('27AABCP0001K1ZM','122025')], TS,
         'GJ Supply Corp',None,None,None,'GJ Supply Corp',None,None,None),
        (3, MH_DUP,'102025',2_500_000, MH_DUP,2_450_000, 49_000.00,0,0,
         None,'C','Y', r7_map[('24AAAAM0001J1ZP','112025')], TS,
         'MH Engineering Works',None,None,None,'MH Engineering Works',None,None,None),
    ]
    tdsa_inv_rows = [
        (1, None,'112025',569_620, D['MH'],605_000,12_100.00,0,0,
         None,'C','Y','INV/005/01','02-11-2025','581012','INV/005/01','02-11-2025','617100',1,TS),
        (2, D['GJ'],'112025',165_000, D['GJ'],170_500, 3_410.00,0,0,
         None,'C','Y','INV/019/01','03-11-2025','168300','INV/019/01','03-11-2025','173910',2,TS),
        (3, MH_DUP,'102025',275_000, MH_DUP,269_500, 5_390.00,0,0,
         None,'C','Y','INV/031/01','01-10-2025','280500','INV/031/01','01-10-2025','274890',3,TS),
    ]
    execute_values(cur, """
        INSERT INTO public.tbl_gst_rtn_r7_tdsa (
            idtbl_gst_rtn_r7_tdsa,ogstin_ded,omonth,oamt_ded,
            gstin_ded,amt_ded,iamt,camt,samt,chksum,source,act_tkn,
            tbl_gst_rtn_r7,inserted_date,deductee_name,idt,inum,ival,
            odeductee_name,oidt,oinum,oival
        ) VALUES %s""", tdsa_rows)
    execute_values(cur, """
        INSERT INTO public.tbl_gst_rtn_r7_tdsa_inv (
            idtbl_gst_rtn_r7_tdsa_inv,ogstin_ded,omonth,oamt_ded,
            gstin_ded,amt_ded,iamt,camt,samt,chksum,source,act_tkn,
            oinum,oidt,oival,inum,idt,ival,idtbl_gst_rtn_r7_tdsa,inserted_date
        ) VALUES %s""", tdsa_inv_rows)

    # tax payable + paid — payable VARIES per return and paid != payable in
    # aggregate (reseed_design.md F5): rid 5 pays 60%, rid 12 pays 85%, rid 7
    # entirely unpaid (no tax_paid / pd_by_cash rows). cgst = sgst kept (law);
    # igst != cgst/sgst on every row.
    PAY_FRAC = {5: 0.60, 12: 0.85}
    UNPAID_R7 = {7}                                      # D3, 102025
    tax_pay_rows = []; tax_paid_rows = []; tax_cash_rows = []; tp_id = 1
    for r7_row in r7_rows:
        rid = r7_row[0]; tran_date = r7_row[3]
        igst_tx = 30_000.00 + 5_000 * ((rid * 7) % 12)
        cgst_tx = sgst_tx = 10_000.00 + 2_500 * ((rid * 5) % 12)
        liab_id = f"2274{rid:08d}"; debit_id = f"DC032025{rid:08d}"
        tax_pay_rows.append((tp_id, liab_id, '30002', tran_date,
            igst_tx,0,0,0,0, cgst_tx,0,0,100.00,0, sgst_tx,0,0,100.00,0,
            0,0,0,0,0, rid, TS))
        if rid not in UNPAID_R7:
            frac = PAY_FRAC.get(rid, 1.0)
            tax_paid_rows.append((tp_id, rid, TS))
            tax_cash_rows.append((tp_id, liab_id, debit_id, '30002', tran_date,
                r2(igst_tx * frac),0,0,0,0, r2(cgst_tx * frac),0,0,100.00,0,
                r2(sgst_tx * frac),0,0,100.00,0,
                0,0,0,0,0, tp_id, TS))
        tp_id += 1

    execute_values(cur, """
        INSERT INTO public.tbl_gst_rtn_r7_tax_pay (
            idtbl_gst_rtn_r7_tax_pay,liab_id,trancd,trandate,
            igst_tx,igst_intr,igst_pen,igst_fee,igst_oth,
            cgst_tx,cgst_intr,cgst_pen,cgst_fee,cgst_oth,
            sgst_tx,sgst_intr,sgst_pen,sgst_fee,sgst_oth,
            cess_tx,cess_intr,cess_pen,cess_fee,cess_oth,
            tbl_gst_rtn_r7,inserted_date
        ) VALUES %s""", tax_pay_rows)
    execute_values(cur,
        "INSERT INTO public.tbl_gst_rtn_r7_tax_paid VALUES %s", tax_paid_rows)
    execute_values(cur, """
        INSERT INTO public.tbl_gst_rtn_r7_tax_paid_pd_by_cash (
            idtbl_gst_rtn_r7_tax_paid_pd_by_cash,liab_id,debit_id,trancd,trandate,
            igst_tx,igst_intr,igst_pen,igst_fee,igst_oth,
            cgst_tx,cgst_intr,cgst_pen,cgst_fee,cgst_oth,
            sgst_tx,sgst_intr,sgst_pen,sgst_fee,sgst_oth,
            cess_tx,cess_intr,cess_pen,cess_fee,cess_oth,
            idtbl_gst_rtn_r7_tax_paid,inserted_date
        ) VALUES %s""", tax_cash_rows)

    print("  GSTR-7: seeded")


# ─── verification + adversarial-invariant checks ─────────────────────────────

def verify(cur) -> None:
    def scalar(sql):
        cur.execute(sql)
        return cur.fetchone()[0]

    print("\nVerification (counts):")
    counts = [
        ("EWB Part-A bills",   "SELECT COUNT(*) FROM public.tbl_ewb_parta_ewb"),
        ("EWB items",          "SELECT COUNT(*) FROM public.tbl_ewb_parta_ewb_itemlist"),
        ("dealers (gstreg)",   "SELECT COUNT(*) FROM common.t_all_delers_api_v_t"),
        ("  cancelled",        "SELECT COUNT(*) FROM common.t_all_delers_api_v_t WHERE canc_dt IS NOT NULL"),
        ("GSTR-3B returns",    "SELECT COUNT(*) FROM public.tbl_gst_rtn_r3b"),
        ("  osupdet rows",     "SELECT COUNT(*) FROM public.tbl_gst_rtn_r3b_sup_details_osupdet"),
        ("  pd_cash lines",    "SELECT COUNT(*) FROM public.tbl_gst_rtn_r3b_tx_pmt_pd_cash"),
        ("GSTR-7 returns",     "SELECT COUNT(*) FROM public.tbl_gst_rtn_r7"),
        ("GSTR-7 TDS rows",    "SELECT COUNT(*) FROM public.tbl_gst_rtn_r7_tds"),
        ("GSTR-7 TDS invoices","SELECT COUNT(*) FROM public.tbl_gst_rtn_r7_tds_inv"),
    ]
    for label, sql in counts:
        print(f"  {label:24s} {scalar(sql)}")

    print("\nInvariant checks:")
    problems = []

    # 1) FK integrity — no orphaned GSTR-3B detail rows
    orphans = scalar("""
        SELECT COUNT(*) FROM public.tbl_gst_rtn_r3b_sup_details_osupdet o
        LEFT JOIN public.tbl_gst_rtn_r3b_sup_details s
          ON o.idtbl_gst_rtn_r3b_sup_details = s.idtbl_gst_rtn_r3b_sup_details
        WHERE s.idtbl_gst_rtn_r3b_sup_details IS NULL""")
    problems += [] if orphans == 0 else [f"orphaned osupdet rows: {orphans}"]

    # 2) EWB argmax distinctness (assval / igstval / InvVal -> 3 different bills)
    a_id = scalar("SELECT idtbl_ewb_parta_ewb FROM public.tbl_ewb_parta_ewb ORDER BY assval DESC LIMIT 1")
    i_id = scalar("SELECT idtbl_ewb_parta_ewb FROM public.tbl_ewb_parta_ewb ORDER BY igstval DESC LIMIT 1")
    v_id = scalar('SELECT idtbl_ewb_parta_ewb FROM public.tbl_ewb_parta_ewb ORDER BY "InvVal" DESC LIMIT 1')
    print(f"  EWB argmax  assval=#{a_id} igst=#{i_id} InvVal=#{v_id}")
    problems += [] if len({a_id, i_id, v_id}) == 3 else [f"EWB argmax collide: {a_id},{i_id},{v_id}"]

    # 3) distinct magnitude per GSTR-3B section table
    sect = {
        'osupdet':    scalar("SELECT SUM(txval) FROM public.tbl_gst_rtn_r3b_sup_details_osupdet"),
        'osupzero':   scalar("SELECT SUM(txval) FROM public.tbl_gst_rtn_r3b_sup_details_osupzero"),
        'osupnilexmp':scalar("SELECT SUM(txval) FROM public.tbl_gst_rtn_r3b_sup_details_osupnilexmp"),
        'osupnongst': scalar("SELECT SUM(txval) FROM public.tbl_gst_rtn_r3b_sup_details_osupnongst"),
        'isuprev':    scalar("SELECT SUM(txval) FROM public.tbl_gst_rtn_r3b_sup_details_isuprev"),
    }
    print("  section SUM(txval): " + " ".join(f"{k}={v:.0f}" for k, v in sect.items()))
    problems += [] if len(set(sect.values())) == 5 else ["section txval sums collide"]

    # 4) exactly one unpaid GSTR-3B return (tx_pmt with no cash and no itc children)
    unpaid = scalar("""
        SELECT COUNT(*) FROM public.tbl_gst_rtn_r3b_tx_pmt t
        WHERE NOT EXISTS (SELECT 1 FROM public.tbl_gst_rtn_r3b_tx_pmt_pd_cash c
                          WHERE c.idtbl_gst_rtn_r3b_tx_pmt = t.idtbl_gst_rtn_r3b_tx_pmt)
          AND NOT EXISTS (SELECT 1 FROM public.tbl_gst_rtn_r3b_tx_pmt_pd_itc i
                          WHERE i.idtbl_gst_rtn_r3b_tx_pmt = t.idtbl_gst_rtn_r3b_tx_pmt)""")
    print(f"  unpaid returns: {unpaid}")
    problems += [] if unpaid >= 1 else ["no unpaid return present"]

    # 5) EWB event-count spread (canceldet/rejdtl/extenddet/transdet asymmetric)
    ev = {t: scalar(f"SELECT COUNT(*) FROM public.tbl_ewb_partb_ewb_{t}")
          for t in ('canceldet', 'rejdtl', 'extenddet', 'transdet')}
    print(f"  EWB events: {ev}")
    expect = {'canceldet': 2, 'rejdtl': 1, 'extenddet': 3, 'transdet': 4}
    problems += [] if ev == expect else [f"EWB event counts {ev} != {expect}"]

    # 6) GSTR-7 duplicate deductee name across GSTINs + >=1 single-return deductee
    dup = scalar("""
        SELECT COUNT(*) FROM (
          SELECT deductee_name FROM public.tbl_gst_rtn_r7_tds
          GROUP BY deductee_name HAVING COUNT(DISTINCT gstin_ded) > 1) q""")
    solo = scalar("""
        SELECT COUNT(*) FROM (
          SELECT gstin_ded FROM public.tbl_gst_rtn_r7_tds
          GROUP BY gstin_ded HAVING COUNT(DISTINCT tbl_gst_rtn_r7) = 1) q""")
    print(f"  GSTR-7 duplicate-name deductees: {dup}, single-return deductees: {solo}")
    problems += [] if dup >= 1 else ["no duplicate-name deductee"]
    problems += [] if solo >= 1 else ["no single-return deductee"]

    # 7) FY decode 2-hop resolves (ret_period -> months -> fy_years)
    unresolved = scalar("""
        SELECT COUNT(*) FROM public.tbl_gst_rtn_r3b r
        LEFT JOIN common.mst_3bd_months_t m ON m.ret_period_fl = r.ret_period
        LEFT JOIN common.mst_fy_years_t   y ON y.flag_fy = m.fy_flag
        WHERE y.flag_fy IS NULL""")
    problems += [] if unresolved == 0 else [f"unresolved FY decode rows: {unresolved}"]

    # ── re-seed round 2 checks (reseed_design.md) ────────────────────────────

    # 8) month factors active: per-month osupdet sums must NOT be uniform
    n_month_sums = scalar("""
        SELECT COUNT(DISTINCT s) FROM (
          SELECT r.ret_period, SUM(o.txval) AS s
          FROM public.tbl_gst_rtn_r3b r
          JOIN public.tbl_gst_rtn_r3b_sup_details sd ON sd.idtbl_gst_rtn_r3b = r.idtbl_gst_rtn_r3b
          JOIN public.tbl_gst_rtn_r3b_sup_details_osupdet o
            ON o.idtbl_gst_rtn_r3b_sup_details = sd.idtbl_gst_rtn_r3b_sup_details
          GROUP BY r.ret_period) q""")
    print(f"  distinct per-month osupdet sums: {n_month_sums}")
    problems += [] if n_month_sums >= 6 else ["per-month osupdet sums too uniform"]

    # 9) RCM spread: returns w/o isuprev row, >=1 zero-txval row, RCM<returns
    total_rtn = scalar("SELECT COUNT(*) FROM public.tbl_gst_rtn_r3b")
    no_rcm_rtn = scalar("""
        SELECT COUNT(*) FROM public.tbl_gst_rtn_r3b r
        JOIN public.tbl_gst_rtn_r3b_sup_details sd ON sd.idtbl_gst_rtn_r3b = r.idtbl_gst_rtn_r3b
        WHERE NOT EXISTS (SELECT 1 FROM public.tbl_gst_rtn_r3b_sup_details_isuprev iv
                          WHERE iv.idtbl_gst_rtn_r3b_sup_details = sd.idtbl_gst_rtn_r3b_sup_details)""")
    zero_rcm = scalar("SELECT COUNT(*) FROM public.tbl_gst_rtn_r3b_sup_details_isuprev WHERE txval = 0")
    pos_rcm = scalar("SELECT COUNT(*) FROM public.tbl_gst_rtn_r3b_sup_details_isuprev WHERE txval > 0")
    print(f"  RCM: {no_rcm_rtn} returns w/o isuprev row, {zero_rcm} zero rows, {pos_rcm} positive of {total_rtn}")
    problems += [] if no_rcm_rtn >= 1 else ["no return without isuprev row"]
    problems += [] if zero_rcm >= 1 else ["no zero-txval isuprev row"]
    problems += [] if pos_rcm < total_rtn else ["every return has RCM > 0"]

    # 10) registered dealers > distinct 3B filers (never-filed dealer exists)
    dealers = scalar("SELECT COUNT(*) FROM common.t_all_delers_api_v_t")
    filers = scalar("SELECT COUNT(DISTINCT gstin) FROM public.tbl_gst_rtn_r3b")
    print(f"  dealers={dealers} vs distinct 3B filers={filers}")
    problems += [] if dealers > filers else ["dealer count == filer count (collision)"]

    # 11) rgtodt is not a cancellation proxy
    n_rgtodt = scalar("SELECT COUNT(*) FROM common.t_all_delers_api_v_t WHERE rgtodt IS NOT NULL")
    n_canc = scalar("SELECT COUNT(*) FROM common.t_all_delers_api_v_t WHERE canc_dt IS NOT NULL")
    n_diff = scalar("""SELECT COUNT(*) FROM common.t_all_delers_api_v_t
                       WHERE canc_dt IS NOT NULL AND rgtodt IS NOT NULL AND canc_dt <> rgtodt""")
    print(f"  rgtodt set on {n_rgtodt}, canc_dt on {n_canc}, rows with canc_dt<>rgtodt: {n_diff}")
    problems += [] if n_rgtodt > n_canc else ["rgtodt-set == canc_dt-set (collision)"]
    problems += [] if n_diff >= 1 else ["no row with canc_dt <> rgtodt"]

    # 12) GSTR-7 payable > paid per component; >=1 unpaid; >=2 partial
    for comp in ('igst_tx', 'cgst_tx', 'sgst_tx'):
        pay = scalar(f"SELECT COALESCE(SUM({comp}),0) FROM public.tbl_gst_rtn_r7_tax_pay")
        paid = scalar(f"SELECT COALESCE(SUM({comp}),0) FROM public.tbl_gst_rtn_r7_tax_paid_pd_by_cash")
        problems += [] if pay > paid else [f"R7 {comp}: payable {pay} !> paid {paid}"]
    r7_unpaid = scalar("""
        SELECT COUNT(*) FROM public.tbl_gst_rtn_r7 r
        WHERE NOT EXISTS (SELECT 1 FROM public.tbl_gst_rtn_r7_tax_paid p
                          WHERE p.tbl_gst_rtn_r7 = r.idtbl_gst_rtn_r7)""")
    print(f"  R7 unpaid returns: {r7_unpaid}")
    problems += [] if r7_unpaid >= 1 else ["no unpaid GSTR-7 return"]

    # 13) GSTR-7 argmax separation (TDS / #gstins / #names / amendments)
    top_tds = scalar("""
        SELECT r.gstin FROM public.tbl_gst_rtn_r7 r
        JOIN public.tbl_gst_rtn_r7_tds t ON t.tbl_gst_rtn_r7 = r.idtbl_gst_rtn_r7
        GROUP BY r.gstin ORDER BY SUM(t.iamt + t.camt + t.samt) DESC LIMIT 1""")
    top_ngstin = scalar("""
        SELECT r.gstin FROM public.tbl_gst_rtn_r7 r
        JOIN public.tbl_gst_rtn_r7_tds t ON t.tbl_gst_rtn_r7 = r.idtbl_gst_rtn_r7
        GROUP BY r.gstin ORDER BY COUNT(DISTINCT t.gstin_ded) DESC LIMIT 1""")
    top_nname = scalar("""
        SELECT r.gstin FROM public.tbl_gst_rtn_r7 r
        JOIN public.tbl_gst_rtn_r7_tds t ON t.tbl_gst_rtn_r7 = r.idtbl_gst_rtn_r7
        GROUP BY r.gstin ORDER BY COUNT(DISTINCT t.deductee_name) DESC LIMIT 1""")
    top_tdsa = scalar("""
        SELECT r.gstin FROM public.tbl_gst_rtn_r7 r
        JOIN public.tbl_gst_rtn_r7_tdsa t ON t.tbl_gst_rtn_r7 = r.idtbl_gst_rtn_r7
        GROUP BY r.gstin ORDER BY SUM(t.iamt + t.camt + t.samt) DESC LIMIT 1""")
    print(f"  R7 argmax  TDS={top_tds} #gstins={top_ngstin} #names={top_nname} tdsa={top_tdsa}")
    problems += [] if top_tds == '03AABCP9999J2DM' else [f"R7 top-TDS moved: {top_tds}"]
    problems += [] if top_ngstin == '27AABCP0001K1ZM' else [f"R7 top-#gstins moved: {top_ngstin}"]
    problems += [] if top_nname == '06AABCE0001M1ZP' else [f"R7 top-#names moved: {top_nname}"]
    problems += [] if top_tdsa != top_tds else ["R7 tdsa argmax == tds argmax (collision)"]

    # 14) filing gap present (SURAT skips 062025)
    gap = scalar("""SELECT COUNT(*) FROM public.tbl_gst_rtn_r3b
                    WHERE gstin = '24AABCE0001D9AA' AND ret_period = '062025'""")
    problems += [] if gap == 0 else ["SURAT 062025 return exists (gap lost)"]

    # 15) 3B top-taxpayer per measure preserved + isuprev/osupdet top-4 differ
    top_turn = scalar("""
        SELECT r.gstin FROM public.tbl_gst_rtn_r3b r
        JOIN public.tbl_gst_rtn_r3b_sup_details sd ON sd.idtbl_gst_rtn_r3b = r.idtbl_gst_rtn_r3b
        JOIN public.tbl_gst_rtn_r3b_sup_details_osupdet o
          ON o.idtbl_gst_rtn_r3b_sup_details = sd.idtbl_gst_rtn_r3b_sup_details
        GROUP BY r.gstin ORDER BY SUM(o.txval) DESC LIMIT 1""")
    top_igst = scalar("""
        SELECT r.gstin FROM public.tbl_gst_rtn_r3b r
        JOIN public.tbl_gst_rtn_r3b_sup_details sd ON sd.idtbl_gst_rtn_r3b = r.idtbl_gst_rtn_r3b
        JOIN public.tbl_gst_rtn_r3b_sup_details_osupdet o
          ON o.idtbl_gst_rtn_r3b_sup_details = sd.idtbl_gst_rtn_r3b_sup_details
        GROUP BY r.gstin ORDER BY SUM(o.iamt) DESC LIMIT 1""")
    top_itc = scalar("""
        SELECT r.gstin FROM public.tbl_gst_rtn_r3b r
        JOIN public.tbl_gst_rtn_r3b_itc_elg e ON e.idtbl_gst_rtn_r3b = r.idtbl_gst_rtn_r3b
        JOIN public.tbl_gst_rtn_r3b_itc_elg_itc_net n
          ON n.idtbl_gst_rtn_r3b_itc_elg = e.idtbl_gst_rtn_r3b_itc_elg
        GROUP BY r.gstin ORDER BY SUM(n.iamt + n.camt + n.samt) DESC LIMIT 1""")
    print(f"  3B argmax  turnover={top_turn} igst={top_igst} itc={top_itc}")
    problems += [] if top_turn == '24AABCE0002E9AA' else [f"3B top-turnover moved: {top_turn}"]
    problems += [] if top_igst == '24AABCE0003F9AA' else [f"3B top-IGST moved: {top_igst}"]
    problems += [] if len({top_turn, top_igst, top_itc}) == 3 else ["3B measure argmaxes collide"]

    cur.execute("""
        SELECT r.gstin FROM public.tbl_gst_rtn_r3b r
        JOIN public.tbl_gst_rtn_r3b_sup_details sd ON sd.idtbl_gst_rtn_r3b = r.idtbl_gst_rtn_r3b
        JOIN public.tbl_gst_rtn_r3b_sup_details_osupdet o
          ON o.idtbl_gst_rtn_r3b_sup_details = sd.idtbl_gst_rtn_r3b_sup_details
        GROUP BY r.gstin ORDER BY SUM(o.txval) DESC LIMIT 4""")
    top4_osup = {row[0] for row in cur.fetchall()}
    cur.execute("""
        SELECT r.gstin FROM public.tbl_gst_rtn_r3b r
        JOIN public.tbl_gst_rtn_r3b_sup_details sd ON sd.idtbl_gst_rtn_r3b = r.idtbl_gst_rtn_r3b
        JOIN public.tbl_gst_rtn_r3b_sup_details_isuprev iv
          ON iv.idtbl_gst_rtn_r3b_sup_details = sd.idtbl_gst_rtn_r3b_sup_details
        GROUP BY r.gstin ORDER BY SUM(iv.txval) DESC LIMIT 4""")
    top4_rcm = {row[0] for row in cur.fetchall()}
    print(f"  top-4 osupdet={sorted(top4_osup)}\n  top-4 isuprev={sorted(top4_rcm)}")
    problems += [] if top4_osup != top4_rcm else ["osupdet/isuprev top-4 sets identical"]

    if problems:
        raise AssertionError("Adversarial-invariant checks FAILED:\n  - " + "\n  - ".join(problems))
    print("\nAll invariant checks PASSED.")


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Ensuring database exists...")
    ensure_db(DSN)

    print("Connecting...")
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute("CREATE SCHEMA IF NOT EXISTS common")
        conn.commit()

        print("Dropping existing objects (clean re-seed)...")
        cur.execute(DROP_ORDER)
        conn.commit()

        print("Creating tables...")
        for ddl in DDL_EWB + DDL_GSTR3B + DDL_GSTREG + DDL_MASTERS + DDL_GSTR7:
            cur.execute(ddl)
        conn.commit()

        print("Seeding data...")
        seed_masters(cur)
        seed_gstreg(cur)
        seed_ewb(cur)
        seed_gstr3b(cur)
        seed_gstr7(cur)

        verify(cur)          # runs inside the txn — a failure rolls the seed back
        conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()

