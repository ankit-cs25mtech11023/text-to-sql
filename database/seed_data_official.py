"""
Seed official GST schemas (EWB, GSTR-3B, GSTR-7) with toy data in PostgreSQL.

Run:  python database/seed_data_official.py
Env:  DATABASE_URL  (default: postgresql://localhost/gst_official)
      Creates the database automatically if it does not exist.
"""
import os
import re
import sys
from datetime import date
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


# ─── DDL ─────────────────────────────────────────────────────────────────────

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

DDL_GSTR3B = [
    "CREATE SCHEMA IF NOT EXISTS live_reports",
    "CREATE SCHEMA IF NOT EXISTS common",
    """CREATE TABLE IF NOT EXISTS common.mst_fy_years_t (
        flag_fy INTEGER PRIMARY KEY,
        desc_year VARCHAR NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS common.mst_3bd_months_t (
        ret_period_fl VARCHAR PRIMARY KEY,
        month_desc VARCHAR,
        quarter VARCHAR
    )""",
    """CREATE TABLE IF NOT EXISTS live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned (
        division CHARACTER VARYING(150),
        "range" CHARACTER VARYING(150),
        unit CHARACTER VARYING(150),
        gstin CHARACTER VARYING(30),
        trdnm CHARACTER VARYING,
        lgnmbzpan CHARACTER VARYING,
        status TEXT,
        rgfmdt DATE,
        rgtodt DATE,
        appr_auth CHARACTER VARYING(20),
        fil_dt DATE,
        ret_period CHARACTER VARYING(10),
        mnth_id INTEGER,
        fy_flag INTEGER NOT NULL,
        return_from_date DATE,
        return_to_date DATE,
        osup_det_txval NUMERIC DEFAULT 0,
        osup_det_samt NUMERIC DEFAULT 0,
        osup_det_camt NUMERIC DEFAULT 0,
        osup_det_iamt NUMERIC DEFAULT 0,
        osup_det_csamt NUMERIC DEFAULT 0,
        osup_zero_txval NUMERIC DEFAULT 0,
        osup_zero_samt NUMERIC DEFAULT 0,
        osup_zero_camt NUMERIC DEFAULT 0,
        osup_zero_iamt NUMERIC DEFAULT 0,
        osup_zero_csamt NUMERIC DEFAULT 0,
        osup_nil_exmp_txval NUMERIC DEFAULT 0,
        osup_nil_exmp_samt NUMERIC DEFAULT 0,
        osup_nil_exmp_camt NUMERIC DEFAULT 0,
        osup_nil_exmp_iamt NUMERIC DEFAULT 0,
        osup_nil_exmp_csamt NUMERIC DEFAULT 0,
        isup_rev_txval NUMERIC DEFAULT 0,
        isup_rev_samt NUMERIC DEFAULT 0,
        isup_rev_camt NUMERIC DEFAULT 0,
        isup_rev_iamt NUMERIC DEFAULT 0,
        isup_rev_csamt NUMERIC DEFAULT 0,
        osup_nongst_txval NUMERIC DEFAULT 0,
        osup_nongst_samt NUMERIC DEFAULT 0,
        osup_nongst_camt NUMERIC DEFAULT 0,
        osup_nongst_iamt NUMERIC DEFAULT 0,
        osup_nongst_csamt NUMERIC DEFAULT 0,
        itc_avl_impg_samt NUMERIC DEFAULT 0,
        itc_avl_impg_iamt NUMERIC DEFAULT 0,
        itc_avl_impg_camt NUMERIC DEFAULT 0,
        itc_avl_impg_csamt NUMERIC DEFAULT 0,
        itc_avl_imps_samt NUMERIC DEFAULT 0,
        itc_avl_imps_iamt NUMERIC DEFAULT 0,
        itc_avl_imps_camt NUMERIC DEFAULT 0,
        itc_avl_imps_csamt NUMERIC DEFAULT 0,
        itc_avl_isrc_samt NUMERIC DEFAULT 0,
        itc_avl_isrc_iamt NUMERIC DEFAULT 0,
        itc_avl_isrc_camt NUMERIC DEFAULT 0,
        itc_avl_isrc_csamt NUMERIC DEFAULT 0,
        itc_avl_isd_samt NUMERIC DEFAULT 0,
        itc_avl_isd_iamt NUMERIC DEFAULT 0,
        itc_avl_isd_camt NUMERIC DEFAULT 0,
        itc_avl_isd_csamt NUMERIC DEFAULT 0,
        itc_avl_oth_samt NUMERIC DEFAULT 0,
        itc_avl_oth_iamt NUMERIC DEFAULT 0,
        itc_avl_oth_camt NUMERIC DEFAULT 0,
        itc_avl_oth_csamt NUMERIC DEFAULT 0,
        itc_rev_rul_samt NUMERIC DEFAULT 0,
        itc_rev_rul_iamt NUMERIC DEFAULT 0,
        itc_rev_rul_camt NUMERIC DEFAULT 0,
        itc_rev_rul_csamt NUMERIC DEFAULT 0,
        itc_rev_oth_samt NUMERIC DEFAULT 0,
        itc_rev_oth_iamt NUMERIC DEFAULT 0,
        itc_rev_oth_camt NUMERIC DEFAULT 0,
        itc_rev_oth_csamt NUMERIC DEFAULT 0,
        itc_net_samt NUMERIC DEFAULT 0,
        itc_net_camt NUMERIC DEFAULT 0,
        itc_net_iamt NUMERIC DEFAULT 0,
        itc_net_csamt NUMERIC DEFAULT 0,
        itc_inelg_rul_camt NUMERIC DEFAULT 0,
        itc_inelg_rul_csamt NUMERIC DEFAULT 0,
        itc_inelg_rul_samt NUMERIC DEFAULT 0,
        itc_inelg_rul_iamt NUMERIC DEFAULT 0,
        itc_inelg_oth_camt NUMERIC DEFAULT 0,
        itc_inelg_oth_csamt NUMERIC DEFAULT 0,
        itc_inelg_oth_samt NUMERIC DEFAULT 0,
        itc_inelg_oth_iamt NUMERIC DEFAULT 0,
        gst_inter NUMERIC DEFAULT 0,
        gst_intra NUMERIC DEFAULT 0,
        non_gst_inter NUMERIC DEFAULT 0,
        non_gst_intra NUMERIC DEFAULT 0,
        itcsetoff_sgst_using_sgst NUMERIC DEFAULT 0,
        itcsetoff_sgst_using_igst NUMERIC DEFAULT 0,
        sgst_cashsetoff NUMERIC DEFAULT 0,
        s_intrpd NUMERIC DEFAULT 0,
        s_lfeepd NUMERIC DEFAULT 0,
        itcsetoff_cgst_using_cgst NUMERIC DEFAULT 0,
        itcsetoff_cgst_using_igst NUMERIC DEFAULT 0,
        cgst_cashsetoff NUMERIC DEFAULT 0,
        c_intrpd NUMERIC DEFAULT 0,
        c_lfeepd NUMERIC DEFAULT 0,
        itcsetoff_igst_using_sgst NUMERIC DEFAULT 0,
        itcsetoff_igst_using_cgst NUMERIC DEFAULT 0,
        itcsetoff_igst_using_igst NUMERIC DEFAULT 0,
        igst_cashsetoff NUMERIC DEFAULT 0,
        i_intrpd NUMERIC DEFAULT 0,
        i_lfeepd NUMERIC DEFAULT 0,
        itcsetoff_cess_using_cess NUMERIC DEFAULT 0,
        cs_intrpd NUMERIC DEFAULT 0,
        cs_lfeepd NUMERIC DEFAULT 0,
        cess_cashsetoff NUMERIC DEFAULT 0,
        samt NUMERIC DEFAULT 0,
        camt NUMERIC DEFAULT 0,
        iamt NUMERIC DEFAULT 0,
        csamt NUMERIC DEFAULT 0,
        state_income NUMERIC DEFAULT 0,
        igst_cashsetoff_rcm NUMERIC DEFAULT 0,
        cgst_cashsetoff_rcm NUMERIC DEFAULT 0,
        sgst_cashsetoff_rcm NUMERIC DEFAULT 0,
        cess_cashsetoff_rcm NUMERIC DEFAULT 0,
        i_intrpd_rcm NUMERIC DEFAULT 0,
        c_intrpd_rcm NUMERIC DEFAULT 0,
        s_intrpd_rcm NUMERIC DEFAULT 0,
        cs_intrpd_rcm NUMERIC DEFAULT 0,
        s_lfeepd_rcm NUMERIC DEFAULT 0,
        c_lfeepd_rcm NUMERIC DEFAULT 0,
        i_lfeepd_rcm NUMERIC DEFAULT 0,
        cs_lfeepd_rcm NUMERIC DEFAULT 0,
        igst_cashsetoff_wo_rcm NUMERIC DEFAULT 0,
        cgst_cashsetoff_wo_rcm NUMERIC DEFAULT 0,
        sgst_cashsetoff_wo_rcm NUMERIC DEFAULT 0,
        cess_cashsetoff_wo_rcm NUMERIC DEFAULT 0,
        i_intrpd_wo_rcm NUMERIC DEFAULT 0,
        c_intrpd_wo_rcm NUMERIC DEFAULT 0,
        s_intrpd_wo_rcm NUMERIC DEFAULT 0,
        cs_intrpd_wo_rcm NUMERIC DEFAULT 0,
        s_lfeepd_wo_rcm NUMERIC DEFAULT 0,
        c_lfeepd_wo_rcm NUMERIC DEFAULT 0,
        i_lfeepd_wo_rcm NUMERIC DEFAULT 0,
        cs_lfeepd_wo_rcm NUMERIC DEFAULT 0,
        eco_sup_txval NUMERIC DEFAULT 0,
        eco_sup_sgst NUMERIC DEFAULT 0,
        eco_sup_cgst NUMERIC DEFAULT 0,
        eco_sup_igst NUMERIC DEFAULT 0,
        eco_sup_cess NUMERIC DEFAULT 0,
        eco_reg_sup_txval NUMERIC DEFAULT 0,
        eco_reg_sup_sgst NUMERIC DEFAULT 0,
        eco_reg_sup_cgst NUMERIC DEFAULT 0,
        eco_reg_sup_igst NUMERIC DEFAULT 0,
        eco_reg_sup_cess NUMERIC DEFAULT 0,
        "current_date" DATE
    ) PARTITION BY LIST (fy_flag)""",
    """CREATE TABLE IF NOT EXISTS live_reports.r3b_t_fy8
       PARTITION OF live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned
       FOR VALUES IN (8)""",
    """CREATE TABLE IF NOT EXISTS live_reports.r3b_t_fy9
       PARTITION OF live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned
       FOR VALUES IN (9)""",
]

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

DROP_ORDER = """
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
DROP TABLE IF EXISTS live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned CASCADE;
DROP TABLE IF EXISTS common.mst_3bd_months_t CASCADE;
DROP TABLE IF EXISTS common.mst_fy_years_t CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tds_inv CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tds CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tdsa_inv CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tdsa CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tax_pay CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tax_paid_pd_by_cash CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7_tax_paid CASCADE;
DROP TABLE IF EXISTS public.tbl_gst_rtn_r7 CASCADE;
"""


# ─── EWB seed data ────────────────────────────────────────────────────────────

def seed_ewb(cur: psycopg2.extensions.cursor) -> None:
    # ── Part-A batches (5 states) ──
    parta_batches = [
        (1, '6',  'HARYANA',     'PARTA', ''),
        (2, '3',  'PUNJAB',      'PARTA', ''),
        (3, '24', 'GUJARAT',     'PARTA', ''),
        (4, '27', 'MAHARASHTRA', 'PARTA', ''),
        (5, '8',  'RAJASTHAN',   'PARTA', ''),
    ]
    execute_values(cur,
        "INSERT INTO public.tbl_ewb_parta VALUES %s",
        parta_batches)

    # ── Part-A EWBs (20 bills) ──
    # Columns: id, ewbno, ewbdt, usertyp, usergstin, transtyp, suptype, ssuptyp,
    #          doctyp, docno, docdt, frgstin, frname, frplac, frpin, frstat,
    #          togstin, toname, toplac, topin, tostat,
    #          assval, cgstval, sgstval, igstval, cessval, cessnonadvolval, otherval,
    #          status, rejstatus, travdist, ssupdesc, "InvVal",
    #          ewbvaliddt, vehtype, despfrstat, shiptostat, idtbl_ewb_parta,
    #          fraddr, toaddr
    #
    # Consignors: C1=Haryana(6), C2=Punjab(3), C3=Gujarat(24), C4=Maharashtra(27), C5=Rajasthan(8)
    # Consignees: B1=Punjab(3), B2=Haryana(6), B3=Gujarat(24), B4=Maharashtra(27), B5=Rajasthan(8)
    C1 = ('06AAECM0001F1ZK', 'Manikaran Power Limited',      'Panchkula',  '134109', '6')
    C2 = ('03AACCN0001H1ZW', 'Punjab Agro Industries Ltd',   'Ludhiana',   '141001', '3')
    C3 = ('24AAAAR0001A9AA', 'Gujarat Textiles Ltd',         'Ahmedabad',  '380001', '24')
    C4 = ('27AABCP0001K1ZM', 'Maharashtra Chemicals Pvt',   'Pune',       '411001', '27')
    C5 = ('08AABCR0001G1Z1', 'Rajasthan Cement Works',       'Jodhpur',    '342001', '8')
    B1 = ('03AACCN0002H1ZW', 'NabhaPower Limited PPL',       'Patiala',    '140401', '3')
    B2 = ('06AAECM0002F1ZK', 'Haryana Textiles Ltd',         'Faridabad',  '121001', '6')
    B3 = ('24AAAAR0002A9AA', 'Gujarat Pharma Ltd',           'Surat',      '395001', '24')
    B4 = ('27AABCP0002K1ZM', 'Mumbai Trading Co',            'Mumbai',     '400001', '27')
    B5 = ('08AABCR0002G1Z1', 'Rajasthan Retail Corp',        'Jaipur',     '302001', '8')

    def ewb_row(eid, ewbno, fr, to, assval, cgst, sgst, igst, status, dist, batch_id, day):
        inv_val = r2(assval + cgst + sgst + igst)
        dt = f"{day:02d}/04/2026 10:30:00 AM"
        valid = f"{min(day+3, 30):02d}/04/2026 11:59:59 PM"
        doc_dt = f"{day:02d}/04/2026"
        doc_no = f"INV-2627-{eid:03d}"
        return (
            eid, ewbno, dt, 'T', fr[0], '1', 'O', '1  ', 'INV',
            doc_no, doc_dt,
            fr[0], fr[1], fr[2], fr[3], fr[4],
            to[0], to[1], to[2], to[3], to[4],
            assval, cgst, sgst, igst, 0, 0, 0,
            status, '', str(dist), '',
            inv_val, valid, 'R', fr[4], to[4], batch_id,
            f"{fr[2]} Industrial Area", f"{to[2]} Warehouse",
        )

    ewbs = [
        # EWBs 1-5: Haryana → various (inter-state IGST), batch=1
        ewb_row( 1,'392234140001',C1,B1, 208700.78,0,0,37566.14,'ACT',150,1, 5),
        ewb_row( 2,'392234140002',C1,B4, 150000.00,0,0,18000.00,'ACT',1200,1, 6),
        ewb_row( 3,'392234140003',C1,B3, 320000.00,0,0,57600.00,'ACT',900,1, 7),
        ewb_row( 4,'392234140004',C1,B1,  84000.00,0,0, 4200.00,'ACT',150,1, 8),
        ewb_row( 5,'392234140005',C1,B5,  95000.00,0,0,17100.00,'ACT',600,1, 9),
        # EWBs 6-10: Punjab (intra/inter), batch=2
        ewb_row( 6,'392234140006',C2,B1, 175000.00,15750,15750,0,'ACT', 80,2,10),
        ewb_row( 7,'392234140007',C2,B1,  62000.00, 3720, 3720,0,'ACT', 60,2,11),
        ewb_row( 8,'392234140008',C2,B2, 280000.00,0,0,50400.00,'ACT',200,2,12),
        ewb_row( 9,'392234140009',C2,B2,  45000.00,0,0,12600.00,'ACT',200,2,13),
        ewb_row(10,'392234140010',C2,B4, 190000.00,0,0,34200.00,'ACT',1400,2,14),
        # EWBs 11-15: Gujarat, batch=3
        ewb_row(11,'392234140011',C3,B3, 130000.00, 7800, 7800,0,'CNL', 50,3,15),
        ewb_row(12,'392234140012',C3,B3, 245000.00,22050,22050,0,'CNL', 70,3,16),
        ewb_row(13,'392234140013',C3,B3, 420000.00,10500,10500,0,'ACT', 90,3,17),
        ewb_row(14,'392234140014',C3,B4, 380000.00,0,0,68400.00,'ACT',500,3,18),
        ewb_row(15,'392234140015',C3,B5, 155000.00,0,0,27900.00,'ACT',700,3,19),
        # EWBs 16-17: Maharashtra, batch=4
        ewb_row(16,'392234140016',C4,B5, 290000.00,0,0,52200.00,'ACT',800,4,20),
        ewb_row(17,'392234140017',C4,B3, 170000.00,0,0,20400.00,'ACT',600,4,21),
        # EWBs 18-20: Rajasthan, batch=5
        ewb_row(18,'392234140018',C5,B3, 310000.00,0,0,55800.00,'CNL',700,5,22),
        ewb_row(19,'392234140019',C5,B4,  88000.00,0,0, 4400.00,'CNL',800,5,23),
        ewb_row(20,'392234140020',C5,B1, 200000.00,0,0,36000.00,'EXP',1100,5,24),
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

    # ── Part-A items ──
    # (id, itemno, prodnam, hsncod, qty, QtyUqc, cgstrt, sgstrt, igstrt, cessrt, assamt, cessadvol, cessnonadvol, ewb_fk)
    items = [
        # EWB 1 (2 items, inter-state 18%)
        ( 1,'1','Wood Pellets',      '44013100','29.43','MTS', 0, 0,18, 0,150000.00, 0, 0, 1),
        ( 2,'2','Cotton Fabric',     '5208',    '500', 'MTS', 0, 0,18, 0, 58700.78, 0, 0, 1),
        # EWB 2 (1 item, inter-state 12%)
        ( 3,'1','Flat Rolled Steel', '7208',    '12',  'MTS', 0, 0,12, 0,150000.00, 0, 0, 2),
        # EWB 3 (2 items, inter-state 18%)
        ( 4,'1','Computers',         '8471',    '100', 'NOS', 0, 0,18, 0,200000.00, 0, 0, 3),
        ( 5,'2','Pharma Products',   '3004',    '50',  'NOS', 0, 0,18, 0,120000.00, 0, 0, 3),
        # EWB 4 (1 item, inter-state 5%)
        ( 6,'1','T-Shirts',          '6109',    '2000','NOS', 0, 0, 5, 0, 84000.00, 0, 0, 4),
        # EWB 5 (1 item, inter-state 18%)
        ( 7,'1','Wood Pellets',      '44013100','15',  'MTS', 0, 0,18, 0, 95000.00, 0, 0, 5),
        # EWB 6 (2 items, intra-state 18%)
        ( 8,'1','Cotton Fabric',     '5208',    '300', 'MTS', 9, 9, 0, 0,100000.00, 0, 0, 6),
        ( 9,'2','Cotton Fabric',     '5208',    '150', 'MTS', 9, 9, 0, 0, 75000.00, 0, 0, 6),
        # EWB 7 (1 item, intra-state 12%)
        (10,'1','Pharma Products',   '3004',    '200', 'NOS', 6, 6, 0, 0, 62000.00, 0, 0, 7),
        # EWB 8 (1 item, inter-state 18%)
        (11,'1','Flat Rolled Steel', '7208',    '20',  'MTS', 0, 0,18, 0,280000.00, 0, 0, 8),
        # EWB 9 (1 item, inter-state 28%)
        (12,'1','Agri Machinery',    '84321000','2',   'NOS', 0, 0,28, 0, 45000.00, 0, 0, 9),
        # EWB 10 (1 item, inter-state 18%)
        (13,'1','Computers',         '8471',    '50',  'NOS', 0, 0,18, 0,190000.00, 0, 0,10),
        # EWB 11 (1 item, intra-state 12%, CNL)
        (14,'1','Cotton Fabric',     '5208',    '200', 'MTS', 6, 6, 0, 0,130000.00, 0, 0,11),
        # EWB 12 (1 item, intra-state 18%, CNL)
        (15,'1','Computers',         '8471',    '30',  'NOS', 9, 9, 0, 0,245000.00, 0, 0,12),
        # EWB 13 (1 item, intra-state 5%)
        (16,'1','T-Shirts',          '6109',    '5000','NOS',2.5,2.5,0, 0,420000.00, 0, 0,13),
        # EWB 14 (1 item, inter-state 18%)
        (17,'1','Flat Rolled Steel', '7208',    '25',  'MTS', 0, 0,18, 0,380000.00, 0, 0,14),
        # EWB 15 (1 item, inter-state 18%)
        (18,'1','Wood Pellets',      '44013100','20',  'MTS', 0, 0,18, 0,155000.00, 0, 0,15),
        # EWB 16 (1 item, inter-state 18%)
        (19,'1','Pharma Products',   '3004',    '500', 'NOS', 0, 0,18, 0,290000.00, 0, 0,16),
        # EWB 17 (1 item, inter-state 12%)
        (20,'1','Cotton Fabric',     '5208',    '400', 'MTS', 0, 0,12, 0,170000.00, 0, 0,17),
        # EWB 18 (1 item, inter-state 18%, CNL)
        (21,'1','Wood Pellets',      '44013100','22',  'MTS', 0, 0,18, 0,310000.00, 0, 0,18),
        # EWB 19 (1 item, inter-state 5%, CNL)
        (22,'1','T-Shirts',          '6109',    '3000','NOS', 0, 0, 5, 0, 88000.00, 0, 0,19),
        # EWB 20 (1 item, inter-state 18%, EXP)
        (23,'1','Computers',         '8471',    '40',  'NOS', 0, 0,18, 0,200000.00, 0, 0,20),
    ]
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_parta_ewb_itemlist (
            idtbl_ewb_parta_ewb_itemlist,itemno,prodnam,hsncod,qty,"QtyUqc",
            cgstrt,sgstrt,igstrt,cessrt,assamt,cessadvol,cessnonadvol,
            idtbl_ewb_parta_ewb
        ) VALUES %s""", items)

    # ── Part-B batches (3 states) ──
    partb_batches = [
        (1, '6',  'HARYANA', 'PARTB', ''),
        (2, '3',  'PUNJAB',  'PARTB', ''),
        (3, '24', 'GUJARAT', 'PARTB', ''),
    ]
    execute_values(cur,
        "INSERT INTO public.tbl_ewb_partb VALUES %s",
        partb_batches)

    # ── Part-B EWBs (12 records, for EWBs 1-10 + 11-12 which are CNL) ──
    # (id, ewb_no, fin_valid_dt, partb_batch_fk)
    partb_ewbs = []
    for i in range(1, 13):
        ewbno = f"39223414{i:04d}"
        batch = 1 if i <= 5 else (2 if i <= 10 else 3)
        day = min(i + 4, 30)
        fin_dt = f"{day:02d}/04/2026 11:59:59 PM"
        partb_ewbs.append((i, ewbno, fin_dt, batch))
    execute_values(cur,
        "INSERT INTO public.tbl_ewb_partb_ewb VALUES %s",
        partb_ewbs)

    # ── Part-B vehicle details (12 rows) ──
    vehicles = ['HR26AB1234','HR26CD5678','HR26EF9012','HR29GH3456','HR29IJ7890',
                'PB10KB0326','PB10LC1234','PB65MD5678','PB07NE9012','PB10OF3456',
                'GJ27TG8978','GJ01PH2345']
    trans_modes = ['1  ','1  ','1  ','1  ','2  ',
                   '1  ','1  ','1  ','1  ','1  ',
                   '1  ','3  ']
    partbdet_rows = []
    for i, (veh, mode) in enumerate(zip(vehicles, trans_modes), start=1):
        ewbno = f"39223414{i:04d}"
        day = min(i + 4, 30)
        upd_dt = f"{day:02d}/04/2026 07:44:00 AM"
        partbdet_rows.append((
            i, veh, 'HARYANA' if i <= 5 else ('PUNJAB' if i <= 10 else 'GUJARAT'),
            '', '', f"0{i}AAECS000{i}H1ZA", upd_dt, mode, '', i, ewbno, '',
        ))
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_partb_ewb_partbdet (
            idtbl_ewb_partb_ewb_partbdet,vehno,frplace,reascd,trdocno,updid,upddt,
            transmode,trdocdt,idtbl_ewb_partb_ewb,ewb_no,valid_till_dt
        ) VALUES %s""", partbdet_rows)

    # ── Cancellation events (EWBs 11 and 12, which have CNL status) ──
    cancel_rows = [
        (1, '392234140011', '15/04/2026 09:00:00 AM', '3', 'Duplicate EWB',   '24AAAAR0003C9AA', 11),
        (2, '392234140012', '16/04/2026 11:30:00 AM', '4', 'Wrong entry',     '24AAAAR0003C9AA', 12),
    ]
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_partb_ewb_canceldet (
            idtbl_ewb_partb_ewb_canceldet,ewb_no,canceldt,cancelreascd,
            cancelreasrem,cancelby,idtbl_ewb_partb_ewb
        ) VALUES %s""", cancel_rows)

    # ── Extension events (EWBs 3, 5, 7) ──
    extend_rows = [
        (1, '09/04/2026 08:00:00 PM','4','Delay in transit','driver001','Ambala',   '80','07/04/2026 11:59:59 PM','6', 3,'392234140003'),
        (2, '11/04/2026 10:00:00 AM','4','Vehicle breakdown','transport2','Bhatinda','120','09/04/2026 11:59:59 PM','3', 5,'392234140005'),
        (3, '13/04/2026 06:00:00 PM','99','Other reason','carrier3','Ludhiana',     '50','11/04/2026 11:59:59 PM','3', 7,'392234140007'),
    ]
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_partb_ewb_extenddet (
            idtbl_ewb_partb_ewb_extenddet,extdt,extreascd,extreasrem,extby,
            frplace,remdist,prev_validdt,frstat,idtbl_ewb_partb_ewb,ewb_no
        ) VALUES %s""", extend_rows)

    # ── Rejection events (EWBs 8 and 9) ──
    rej_rows = [
        (1,'392234140008','06AAECM0002F1ZK','12/04/2026 01:19:49 PM', 8),
        (2,'392234140009','06AAECM0002F1ZK','13/04/2026 03:45:00 PM', 9),
    ]
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_partb_ewb_rejdtl (
            idtbl_ewb_partb_ewb_rejdtl,ewb_no,rejgstin,rejdt,idtbl_ewb_partb_ewb
        ) VALUES %s""", rej_rows)

    # ── Transporter change events (EWBs 1, 4, 6) ──
    trans_rows = [
        (1,'88AAECS0001H1ZA','API_HARYANA     ','05/04/2026 01:42:00 PM', 1,'392234140001'),
        (2,'08AAICK0001B1ZE','API_PUNJAB      ','08/04/2026 09:15:00 AM', 4,'392234140004'),
        (3,'03AADFP0001Q1ZR','API_HARYANA     ','10/04/2026 11:00:00 AM', 6,'392234140006'),
    ]
    execute_values(cur, """
        INSERT INTO public.tbl_ewb_partb_ewb_transdet (
            idtbl_ewb_partb_ewb_transdet,transid,updid,upddt,
            idtbl_ewb_partb_ewb,ewb_no
        ) VALUES %s""", trans_rows)

    print("  EWB: seeded")


# ─── GSTR-3B seed data ────────────────────────────────────────────────────────

# Column list (145 columns in DDL order)
R3B_COLS = (
    'division,"range",unit,gstin,trdnm,lgnmbzpan,status,rgfmdt,rgtodt,appr_auth,'
    'fil_dt,ret_period,mnth_id,fy_flag,return_from_date,return_to_date,'
    'osup_det_txval,osup_det_samt,osup_det_camt,osup_det_iamt,osup_det_csamt,'
    'osup_zero_txval,osup_zero_samt,osup_zero_camt,osup_zero_iamt,osup_zero_csamt,'
    'osup_nil_exmp_txval,osup_nil_exmp_samt,osup_nil_exmp_camt,osup_nil_exmp_iamt,osup_nil_exmp_csamt,'
    'isup_rev_txval,isup_rev_samt,isup_rev_camt,isup_rev_iamt,isup_rev_csamt,'
    'osup_nongst_txval,osup_nongst_samt,osup_nongst_camt,osup_nongst_iamt,osup_nongst_csamt,'
    'itc_avl_impg_samt,itc_avl_impg_iamt,itc_avl_impg_camt,itc_avl_impg_csamt,'
    'itc_avl_imps_samt,itc_avl_imps_iamt,itc_avl_imps_camt,itc_avl_imps_csamt,'
    'itc_avl_isrc_samt,itc_avl_isrc_iamt,itc_avl_isrc_camt,itc_avl_isrc_csamt,'
    'itc_avl_isd_samt,itc_avl_isd_iamt,itc_avl_isd_camt,itc_avl_isd_csamt,'
    'itc_avl_oth_samt,itc_avl_oth_iamt,itc_avl_oth_camt,itc_avl_oth_csamt,'
    'itc_rev_rul_samt,itc_rev_rul_iamt,itc_rev_rul_camt,itc_rev_rul_csamt,'
    'itc_rev_oth_samt,itc_rev_oth_iamt,itc_rev_oth_camt,itc_rev_oth_csamt,'
    'itc_net_samt,itc_net_camt,itc_net_iamt,itc_net_csamt,'
    'itc_inelg_rul_camt,itc_inelg_rul_csamt,itc_inelg_rul_samt,itc_inelg_rul_iamt,'
    'itc_inelg_oth_camt,itc_inelg_oth_csamt,itc_inelg_oth_samt,itc_inelg_oth_iamt,'
    'gst_inter,gst_intra,non_gst_inter,non_gst_intra,'
    'itcsetoff_sgst_using_sgst,itcsetoff_sgst_using_igst,sgst_cashsetoff,s_intrpd,s_lfeepd,'
    'itcsetoff_cgst_using_cgst,itcsetoff_cgst_using_igst,cgst_cashsetoff,c_intrpd,c_lfeepd,'
    'itcsetoff_igst_using_sgst,itcsetoff_igst_using_cgst,itcsetoff_igst_using_igst,igst_cashsetoff,i_intrpd,i_lfeepd,'
    'itcsetoff_cess_using_cess,cs_intrpd,cs_lfeepd,cess_cashsetoff,'
    'samt,camt,iamt,csamt,state_income,'
    'igst_cashsetoff_rcm,cgst_cashsetoff_rcm,sgst_cashsetoff_rcm,cess_cashsetoff_rcm,'
    'i_intrpd_rcm,c_intrpd_rcm,s_intrpd_rcm,cs_intrpd_rcm,'
    's_lfeepd_rcm,c_lfeepd_rcm,i_lfeepd_rcm,cs_lfeepd_rcm,'
    'igst_cashsetoff_wo_rcm,cgst_cashsetoff_wo_rcm,sgst_cashsetoff_wo_rcm,cess_cashsetoff_wo_rcm,'
    'i_intrpd_wo_rcm,c_intrpd_wo_rcm,s_intrpd_wo_rcm,cs_intrpd_wo_rcm,'
    's_lfeepd_wo_rcm,c_lfeepd_wo_rcm,i_lfeepd_wo_rcm,cs_lfeepd_wo_rcm,'
    'eco_sup_txval,eco_sup_sgst,eco_sup_cgst,eco_sup_igst,eco_sup_cess,'
    'eco_reg_sup_txval,eco_reg_sup_sgst,eco_reg_sup_cgst,eco_reg_sup_igst,eco_reg_sup_cess,'
    '"current_date"'
)

# Return periods: MMYYYY → (mnth_id, fy_flag, from_date, to_date, fil_date)
PERIODS = {
    '042024': (82, 8, date(2024, 4, 1), date(2024, 4, 30), date(2024, 5, 20)),
    '052024': (83, 8, date(2024, 5, 1), date(2024, 5, 31), date(2024, 6, 20)),
    '062024': (84, 8, date(2024, 6, 1), date(2024, 6, 30), date(2024, 7, 20)),
    '072024': (85, 8, date(2024, 7, 1), date(2024, 7, 31), date(2024, 8, 20)),
    '082024': (86, 8, date(2024, 8, 1), date(2024, 8, 31), date(2024, 9, 20)),
    '092024': (87, 8, date(2024, 9, 1), date(2024, 9, 30), date(2024, 10,20)),
    '042025': (94, 9, date(2025, 4, 1), date(2025, 4, 30), date(2025, 5, 20)),
    '052025': (95, 9, date(2025, 5, 1), date(2025, 5, 31), date(2025, 6, 20)),
    '062025': (96, 9, date(2025, 6, 1), date(2025, 6, 30), date(2025, 7, 20)),
}


def make_r3b_row(profile: dict, ret_period: str) -> tuple:
    mnth_id, fy_flag, ret_from, ret_to, fil_dt = PERIODS[ret_period]
    txval   = profile['txval']
    rate    = profile['rate']       # CGST rate (9% for 18% GST)
    ifrac   = profile['igst_frac']  # fraction of sales that are inter-state
    nil_frac= profile.get('nil_frac', 0)

    intra = r2(txval * (1 - ifrac))
    inter = r2(txval * ifrac)

    # 3.1(a) outward
    o_samt = r2(intra * rate)
    o_camt = o_samt
    o_iamt = r2(inter * rate * 2)   # IGST = both legs

    # 3.1(c) nil/exempt
    nil_txval = r2(txval * nil_frac)

    # 3.1(d) RCM inward (intra-state services, 18%)
    rcm_txval = r2(txval * 0.015)
    rcm_s = rcm_c = r2(rcm_txval * 0.09)

    # 4A(3) ITC from RCM (claimed back same amount)
    isrc_s = rcm_s
    isrc_c = rcm_c

    # 4A(5) ITC from other purchases (~60% of sales at same rate)
    pur  = r2(txval * 0.60)
    oth_s = r2(pur * rate * (1 - ifrac))
    oth_i = r2(pur * ifrac * rate * 2)
    oth_c = oth_s

    # 4C net ITC
    net_s = r2(oth_s + isrc_s)
    net_c = r2(oth_c + isrc_c)
    net_i = oth_i

    # Tax totals (6.1)
    t_s = r2(o_samt + rcm_s)   # total SGST payable
    t_c = r2(o_camt + rcm_c)   # total CGST payable
    t_i = o_iamt                # total IGST payable

    # ITC setoffs
    itc_off_s = min(net_s, t_s)
    sgst_cash = r2(max(0, t_s - net_s))
    itc_off_c = min(net_c, t_c)
    cgst_cash = r2(max(0, t_c - net_c))
    igst_off  = min(net_i, t_i)
    igst_cash = r2(max(0, t_i - net_i))

    # RCM cash splits (RCM must always be paid in cash)
    rcm_c_cash = rcm_c
    rcm_s_cash = rcm_s
    cgst_wo = r2(cgst_cash - rcm_c_cash)
    sgst_wo = r2(sgst_cash - rcm_s_cash)

    state_income = sgst_cash  # simplified (no IGST cross-credit flows)

    MV_DATE = date(2026, 5, 1)

    return (
        # geo + master (10)
        profile['div'], profile['rng'], profile['unit'],
        profile['gstin'], profile['trdnm'], profile['lgnm'],
        'Active', date(2017, 7, 1), None, profile['auth'],
        # period (6)
        fil_dt, ret_period, mnth_id, fy_flag, ret_from, ret_to,
        # 3.1(a) outward (5)
        txval, o_samt, o_camt, o_iamt, 0,
        # 3.1(b) zero-rated (5)
        0, 0, 0, 0, 0,
        # 3.1(c) nil/exempt (5)
        nil_txval, 0, 0, 0, 0,
        # 3.1(d) RCM (5)
        rcm_txval, rcm_s, rcm_c, 0, 0,
        # 3.1(e) non-GST (5)
        0, 0, 0, 0, 0,
        # 4A(1) ITC import goods (4)
        0, 0, 0, 0,
        # 4A(2) ITC import services (4)
        0, 0, 0, 0,
        # 4A(3) ITC RCM (4): samt, iamt, camt, csamt
        isrc_s, 0, isrc_c, 0,
        # 4A(4) ITC ISD (4)
        0, 0, 0, 0,
        # 4A(5) ITC other (4): samt, iamt, camt, csamt
        oth_s, oth_i, oth_c, 0,
        # 4B(1) reversed rules (4)
        0, 0, 0, 0,
        # 4B(2) reversed others (4)
        0, 0, 0, 0,
        # 4C net ITC (4)
        net_s, net_c, net_i, 0,
        # 4D(1) inelig rul (4): camt,csamt,samt,iamt
        0, 0, 0, 0,
        # 4D(2) inelig oth (4): camt,csamt,samt,iamt
        0, 0, 0, 0,
        # Sec 5 exempt inward (4)
        0, 0, 0, 0,
        # SGST setoffs (5)
        itc_off_s, 0, sgst_cash, 0, 0,
        # CGST setoffs (5)
        itc_off_c, 0, cgst_cash, 0, 0,
        # IGST setoffs (6)
        0, 0, igst_off, igst_cash, 0, 0,
        # CESS (4)
        0, 0, 0, 0,
        # Tax totals (4) + state income (1)
        t_s, t_c, t_i, 0,
        state_income,
        # 6.1(B) RCM cash (12): igst,cgst,sgst,cess × (cash,intr,fee)
        0, rcm_c_cash, rcm_s_cash, 0,
        0, 0, 0, 0,
        0, 0, 0, 0,
        # 6.1(A) non-RCM cash (12)
        0, cgst_wo, sgst_wo, 0,
        0, 0, 0, 0,
        0, 0, 0, 0,
        # ECO 3.1.1(i) (5)
        0, 0, 0, 0, 0,
        # ECO 3.1.1(ii) (5)
        0, 0, 0, 0, 0,
        # current_date (1)
        MV_DATE,
    )


def seed_gstr3b(cur: psycopg2.extensions.cursor) -> None:
    # ── decode master tables ──
    execute_values(cur,
        "INSERT INTO common.mst_fy_years_t VALUES %s ON CONFLICT DO NOTHING",
        [(6,'2022-23'),(7,'2023-24'),(8,'2024-25'),(9,'2025-26'),(10,'2026-27')])

    months_data = [
        ('042024','April','Q1'),('052024','May','Q1'),('062024','June','Q1'),
        ('072024','July','Q2'),('082024','August','Q2'),('092024','September','Q2'),
        ('042025','April','Q1'),('052025','May','Q1'),('062025','June','Q1'),
    ]
    execute_values(cur,
        "INSERT INTO common.mst_3bd_months_t VALUES %s ON CONFLICT DO NOTHING",
        months_data)

    # ── taxpayer profiles ──
    PROFILES = [
        dict(gstin='24AAAAR0001A9AA', trdnm='SANGH TEXTILES LTD',
             lgnm='SANGH TEXTILES LIMITED AHMEDABAD',
             div='Division 1 (ABD)', rng='Range 1 (ABD)', unit='Ghatak 1 (ABD)',
             auth='STATE', txval=2_210_664, rate=0.09, igst_frac=0.0, nil_frac=0.02),
        dict(gstin='24AAAAR0002B9AA', trdnm='PATEL CHEMICALS LTD',
             lgnm='PATEL CHEMICALS LIMITED',
             div='Division 1 (ABD)', rng='Range 1 (ABD)', unit='Ghatak 2 (ABD)',
             auth='STATE', txval=800_000, rate=0.09, igst_frac=0.30),
        dict(gstin='24AAAAR0003C9AA', trdnm='GUJARAT PHARMA CORP',
             lgnm='GUJARAT PHARMACEUTICAL CORPORATION',
             div='Division 1 (ABD)', rng='Range 2 (ABD)', unit='Ghatak 3 (ABD)',
             auth='CENTER', txval=1_500_000, rate=0.06, igst_frac=0.10),
        dict(gstin='24AABCE0001D9AA', trdnm='SURAT TEXTILES PVT LTD',
             lgnm='SURAT TEXTILES PRIVATE LIMITED',
             div='Division 2 (ABD)', rng='Range 3 (ABD)', unit='Ghatak 4 (ABD)',
             auth='STATE', txval=1_200_000, rate=0.09, igst_frac=0.0),
        dict(gstin='24AABCE0002E9AA', trdnm='AHMEDABAD STEEL WORKS',
             lgnm='AHMEDABAD STEEL WORKS LTD',
             div='Division 2 (ABD)', rng='Range 3 (ABD)', unit='Ghatak 5 (ABD)',
             auth='STATE', txval=3_000_000, rate=0.09, igst_frac=0.50),
        dict(gstin='24AABCE0003F9AA', trdnm='GUJARAT CEMENT LTD',
             lgnm='GUJARAT CEMENT LIMITED',
             div='Division 2 (ABD)', rng='Range 4 (ABD)', unit='Ghatak 6 (ABD)',
             auth='CENTER', txval=2_500_000, rate=0.09, igst_frac=0.20),
        dict(gstin='24AACCD0001G9AA', trdnm='BARODA FOODS LTD',
             lgnm='BARODA FOODS LIMITED',
             div='Division 3 (ABD)', rng='Range 5 (ABD)', unit='Ghatak 7 (ABD)',
             auth='STATE', txval=500_000, rate=0.025, igst_frac=0.0, nil_frac=0.15),
        dict(gstin='24AACCD0002H9AA', trdnm='RAJKOT AUTO PARTS',
             lgnm='RAJKOT AUTO PARTS PVT LTD',
             div='Division 3 (ABD)', rng='Range 5 (ABD)', unit='Ghatak 8 (ABD)',
             auth='STATE', txval=1_800_000, rate=0.14, igst_frac=0.40),
    ]

    # fy_flag=8: all 8 taxpayers × 6 months
    rows = []
    for p in PROFILES:
        for rp in ['042024','052024','062024','072024','082024','092024']:
            rows.append(make_r3b_row(p, rp))

    # fy_flag=9: first 5 taxpayers × 3 months
    for p in PROFILES[:5]:
        for rp in ['042025','052025','062025']:
            rows.append(make_r3b_row(p, rp))

    execute_values(cur,
        f"INSERT INTO live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned"
        f" ({R3B_COLS}) VALUES %s",
        rows)

    print("  GSTR-3B: seeded")


# ─── GSTR-7 seed data ─────────────────────────────────────────────────────────

def seed_gstr7(cur: psycopg2.extensions.cursor) -> None:
    TS = '2025-10-14 12:12:23.991941+05:30'

    # ── Main returns: 4 deductors × 3 periods = 12 rows ──
    deductors = [
        ('03AABCP9999J2DM', 'Punjab Dept Public Works'),
        ('06AABCE0001M1ZP', 'Haryana Power Corporation'),
        ('27AABCP0001K1ZM', 'Maharashtra Water Authority'),
        ('24AAAAM0001J1ZP', 'Gujarat Infrastructure Corp'),
    ]
    periods = ['102025', '112025', '122025']

    r7_rows = []
    r7_id = 1
    r7_map = {}   # (gstin, fp) → idtbl_gst_rtn_r7
    for gstin, _ in deductors:
        for fp in periods:
            day = 29 if fp == '102025' else (28 if fp == '112025' else 28)
            mm = fp[:2]; yyyy = fp[2:]
            fil = f"{day}-{mm}-{yyyy}"
            r7_rows.append((r7_id, fp, gstin, fil, TS))
            r7_map[(gstin, fp)] = r7_id
            r7_id += 1

    execute_values(cur,
        "INSERT INTO public.tbl_gst_rtn_r7 VALUES %s",
        r7_rows)

    # ── TDS rows: 2-3 deductees per return ──
    tds_rows = []
    tds_inv_rows = []
    tds_id = 1
    tds_inv_id = 1

    # Deductee GSTINs
    D = {
        'WB':  '19AABCK9999C1ZI',
        'PB':  '03AADFP9999Q1ZR',
        'MH':  '27AAACC9999G1ZD',
        'HR':  '06AAACK0000K1ZF',
        'GJ':  '24AAAAM0002J1ZS',
    }

    def tds_entry(r7_fk, ded_gstin, ded_name, amt, is_inter: bool):
        nonlocal tds_id, tds_inv_id
        if is_inter:
            iamt, camt, samt = r2(amt * 0.02), 0, 0
        else:
            iamt, camt, samt = 0, r2(amt * 0.01), r2(amt * 0.01)
        tds_rows.append((tds_id, ded_gstin, amt, iamt, camt, samt,
                         None, r7_fk, TS, ded_name, None, None, None))

        # 2 invoices per TDS row
        inv_amt = r2(amt * 0.55)
        for k in range(1, 3):
            iv = r2(inv_amt * k * 1.18)
            ad = r2(inv_amt * k)
            i_i = r2(ad * 0.02) if is_inter else 0
            c_a = r2(ad * 0.01) if not is_inter else 0
            s_a = c_a
            tds_inv_rows.append((
                tds_inv_id, f"INV/{r7_fk:03d}/{k:02d}",
                f"2{k:02d}-10-2025", iv, ad, i_i, c_a, s_a,
                'N', None, tds_id, TS,
            ))
            tds_inv_id += 1
        tds_id += 1

    # Deductor 1 (Punjab PWD) — per period
    for fp in periods:
        fk = r7_map[('03AABCP9999J2DM', fp)]
        tds_entry(fk, D['WB'], 'WB Contractors Ltd',   7_669_081, True)   # inter-state
        tds_entry(fk, D['PB'], 'Punjab IT Services',   2_191_166, False)  # intra-state

    # Deductor 2 (Haryana Power)
    for fp in periods:
        fk = r7_map[('06AABCE0001M1ZP', fp)]
        tds_entry(fk, D['MH'], 'MH Engineering Works', 5_000_000, True)
        tds_entry(fk, D['HR'], 'HR Civil Contractors',  1_000_000, False)

    # Deductor 3 (Maharashtra Water)
    for fp in periods:
        fk = r7_map[('27AABCP0001K1ZM', fp)]
        tds_entry(fk, D['GJ'], 'GJ Supply Corp',        3_500_000, True)
        tds_entry(fk, D['PB'], 'Punjab Suppliers',       800_000, True)
        tds_entry(fk, D['MH'], 'MH Local Vendor',        500_000, False)

    # Deductor 4 (Gujarat Infra)
    for fp in periods:
        fk = r7_map[('24AAAAM0001J1ZP', fp)]
        tds_entry(fk, D['GJ'], 'Ahmedabad Constructions',4_200_000, False)
        tds_entry(fk, D['MH'], 'Pune Infrastructure Co', 2_800_000, True)

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

    # ── TDSA (amendments): deductor 1, nov period amends oct ──
    tdsa_rows = []
    tdsa_inv_rows = []
    tdsa_id = 1
    tdsa_inv_id = 1

    oct_fk_d1 = r7_map[('03AABCP9999J2DM', '102025')]
    nov_fk_d1 = r7_map[('03AABCP9999J2DM', '112025')]

    tdsa_rows.append((
        1, D['WB'], '102025', 7_669_081,
        D['WB'], 7_500_000, 150_000.00, 0, 0,
        None, 'C', 'Y', nov_fk_d1, TS,
        'WB Contractors Ltd', None, None, None,
        'WB Contractors Ltd', None, None, None,
    ))
    tdsa_inv_rows.append((
        1, D['WB'], '102025', 486_780,
        D['WB'], 486_780, 0, 4_867.80, 4_867.80,
        None, 'C', 'Y',
        'INV/001/01', '01-10-2025', '496516',
        'INV/001/01', '01-10-2025', '496516',
        1, TS,
    ))

    # Deductor 2, dec period amends nov
    nov_fk_d2 = r7_map[('06AABCE0001M1ZP', '112025')]
    dec_fk_d2 = r7_map[('06AABCE0001M1ZP', '122025')]
    tdsa_rows.append((
        2, D['MH'], '112025', 5_000_000,
        D['MH'], 4_800_000, 96_000.00, 0, 0,
        None, 'C', 'Y', dec_fk_d2, TS,
        'MH Engineering Works', None, None, None,
        'MH Engineering Works', None, None, None,
    ))
    tdsa_inv_rows.append((
        2, None, '112025', 569_620,
        D['MH'], 569_620, 0, 0, 0,
        None, 'C', 'Y',
        'INV/005/01', '02-11-2025', '581012',
        'INV/005/01', '02-11-2025', '581012',
        2, TS,
    ))

    execute_values(cur, """
        INSERT INTO public.tbl_gst_rtn_r7_tdsa (
            idtbl_gst_rtn_r7_tdsa,ogstin_ded,omonth,oamt_ded,
            gstin_ded,amt_ded,iamt,camt,samt,
            chksum,source,act_tkn,tbl_gst_rtn_r7,inserted_date,
            deductee_name,idt,inum,ival,
            odeductee_name,oidt,oinum,oival
        ) VALUES %s""", tdsa_rows)

    execute_values(cur, """
        INSERT INTO public.tbl_gst_rtn_r7_tdsa_inv (
            idtbl_gst_rtn_r7_tdsa_inv,ogstin_ded,omonth,oamt_ded,
            gstin_ded,amt_ded,iamt,camt,samt,
            chksum,source,act_tkn,
            oinum,oidt,oival,inum,idt,ival,
            idtbl_gst_rtn_r7_tdsa,inserted_date
        ) VALUES %s""", tdsa_inv_rows)

    # ── Tax payable + paid (one per return) ──
    tax_pay_rows = []
    tax_paid_rows = []
    tax_cash_rows = []
    tp_id = 1

    for r7_row in r7_rows:
        rid = r7_row[0]
        # Compute a plausible payable from TDS sums for this return
        # Simple: use 50K IGST or 20K CGST+SGST as placeholder
        igst_tx = 50_000.00
        cgst_tx = 20_000.00
        sgst_tx = 20_000.00

        liab_id = f"2274{rid:08d}"
        debit_id = f"DC032025{rid:08d}"
        tran_date = r7_row[3]  # filing date

        tax_pay_rows.append((
            tp_id, liab_id, '30002', tran_date,
            igst_tx, 0, 0, 0, 0,
            cgst_tx, 0, 0, 100.00, 0,
            sgst_tx, 0, 0, 100.00, 0,
            0, 0, 0, 0, 0,
            rid, TS,
        ))
        tax_paid_rows.append((tp_id, rid, TS))
        tax_cash_rows.append((
            tp_id, liab_id, debit_id, '30002', tran_date,
            igst_tx, 0, 0, 0, 0,
            cgst_tx, 0, 0, 100.00, 0,
            sgst_tx, 0, 0, 100.00, 0,
            0, 0, 0, 0, 0,
            tp_id, TS,
        ))
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
        "INSERT INTO public.tbl_gst_rtn_r7_tax_paid VALUES %s",
        tax_paid_rows)

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


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Ensuring database exists...")
    ensure_db(DSN)

    print("Connecting...")
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # Create schemas first (before DROP — partitions live in live_reports)
        cur.execute("CREATE SCHEMA IF NOT EXISTS live_reports")
        cur.execute("CREATE SCHEMA IF NOT EXISTS common")
        conn.commit()

        print("Dropping existing tables (clean re-seed)...")
        cur.execute(DROP_ORDER)
        conn.commit()

        print("Creating tables...")
        for ddl in DDL_EWB + DDL_GSTR3B + DDL_GSTR7:
            cur.execute(ddl)
        conn.commit()

        print("Seeding data...")
        seed_ewb(cur)
        seed_gstr3b(cur)
        seed_gstr7(cur)
        conn.commit()

        # ── verification counts ──
        checks = [
            ("EWB Part-A bills",     "SELECT COUNT(*) FROM public.tbl_ewb_parta_ewb"),
            ("EWB items",            "SELECT COUNT(*) FROM public.tbl_ewb_parta_ewb_itemlist"),
            ("EWB Part-B events",    "SELECT COUNT(*) FROM public.tbl_ewb_partb_ewb"),
            ("EWB cancellations",    "SELECT COUNT(*) FROM public.tbl_ewb_partb_ewb_canceldet"),
            ("GSTR-3B returns",      "SELECT COUNT(*) FROM live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned"),
            ("GSTR-3B fy8 returns",  "SELECT COUNT(*) FROM live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned WHERE fy_flag=8"),
            ("GSTR-3B fy9 returns",  "SELECT COUNT(*) FROM live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned WHERE fy_flag=9"),
            ("GSTR-7 returns",       "SELECT COUNT(*) FROM public.tbl_gst_rtn_r7"),
            ("GSTR-7 TDS rows",      "SELECT COUNT(*) FROM public.tbl_gst_rtn_r7_tds"),
            ("GSTR-7 TDS invoices",  "SELECT COUNT(*) FROM public.tbl_gst_rtn_r7_tds_inv"),
        ]
        print("\nVerification:")
        for label, sql in checks:
            cur.execute(sql)
            print(f"  {label:30s} {cur.fetchone()[0]}")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
