"""Generate the staging layer.

Staging is mechanical: one model per source table, cleaning only. Writing 44
near-identical models by hand invites inconsistency in exactly the place where
consistency is the whole point, so the models are generated from the column
spec below and committed. The spec is the source of truth for source->staging
renames; re-run this script after editing it.

    python scripts/generate_staging.py

Transform codes
---------------
key    trim() - X3 CHAR-padded key (README landmine 1)
str    nullif(trim(x), '')
int    cast to bigint
num    cast to decimal(18,4)
date   pass through
sdate  sentinel-guarded date: 1753-01-01 -> null (README landmine 2)
bool   pass through
pdate  Paycom MM/DD/YYYY string -> date (README landmine 10)
pnum   Paycom string amount -> decimal
hsnum  HubSpot string property -> double, non-numeric -> null (landmine 6)
raw    pass through untouched
"""
import json
import os
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLS = json.load(open(os.path.join(ROOT, ".cache_columns.json"))) if os.path.exists(
    os.path.join(ROOT, ".cache_columns.json")) else None

SENTINEL = "1753-01-01"


def q(col):
    return f'"{col}"'


def expr(col, kind):
    c = q(col)
    if kind == "key":
        return f"nullif(trim({c}), '')"
    if kind == "str":
        return f"nullif(trim({c}), '')"
    if kind == "int":
        return f"cast({c} as bigint)"
    if kind == "num":
        return f"cast({c} as decimal(18, 4))"
    if kind == "date":
        return c
    if kind == "sdate":
        return f"nullif({c}, date '{SENTINEL}')"
    if kind == "bool":
        return f"cast({c} as boolean)"
    if kind == "pdate":
        return f"try_strptime(nullif(trim({c}), ''), '%m/%d/%Y')::date"
    if kind == "pnum":
        return f"try_cast(nullif(trim({c}), '') as decimal(18, 4))"
    if kind == "hsnum":
        return f"try_cast(nullif(trim({c}), '') as double)"
    if kind == "raw":
        return c
    raise ValueError(kind)


# ---------------------------------------------------------------------------
# Spec: (schema, table) -> dict(grain=..., cols=[(source_col, alias, kind)],
#                               menus=[(int_alias, chapter, label_alias)],
#                               extra=[(alias, sql)])
# ---------------------------------------------------------------------------
SPEC = {}


def t(schema, table, grain, cols, menus=(), extra=(), model=None):
    SPEC[(schema, table)] = dict(grain=grain, cols=cols, menus=list(menus),
                                 extra=list(extra), model=model)


# --------------------------------- sage_x3 --------------------------------
t("sage_x3", "COMPANY", "One row per legal entity.", [
    ("CPY_0", "company_code", "key"),
    ("CPYNAM_0", "company_name", "str"),
    ("CRY_0", "country_code", "str"),
    ("LEG_0", "legislation_code", "str"),
    ("CPYLOG_0", "is_logistics_flag", "int"),
])

t("sage_x3", "FACILITY", "One row per site (X3 facility).", [
    ("FCY_0", "site_code", "key"),
    ("FCYSHO_0", "site_short_name", "str"),
    ("FCYNAM_0", "site_name", "str"),
    ("LEGCPY_0", "company_code", "key"),
    ("CRY_0", "country_code", "str"),
    ("CTY_0", "city", "str"),
    ("SAT_0", "state_province", "str"),
    ("FCYSTO_0", "is_stock_site_code", "int"),
    ("FCYSAL_0", "is_sales_site_code", "int"),
    ("FCYPUR_0", "is_purchase_site_code", "int"),
], extra=[
    ("is_stock_site", 'cast("FCYSTO_0" = 2 as boolean)'),
    ("is_sales_site", 'cast("FCYSAL_0" = 2 as boolean)'),
    ("is_purchase_site", 'cast("FCYPUR_0" = 2 as boolean)'),
])

t("sage_x3", "BPARTNER", "One row per business partner.", [
    ("BPRNUM_0", "partner_code", "key"),
    ("BPRNAM_0", "partner_name", "str"),
    ("BPRNAM_1", "partner_name_2", "str"),
    ("BPCFLG_0", "is_customer_code", "int"),
    ("BPSFLG_0", "is_supplier_code", "int"),
    ("CRY_0", "country_code", "str"),
    ("CUR_0", "currency_code", "str"),
    ("BPRLOG_0", "is_active_code", "int"),
    ("UPDTICK_0", "update_tick", "int"),
], extra=[
    ("is_customer", 'cast("BPCFLG_0" = 2 as boolean)'),
    ("is_supplier", 'cast("BPSFLG_0" = 2 as boolean)'),
])

t("sage_x3", "BPCUSTOMER", "One row per customer account.", [
    ("BPCNUM_0", "customer_code", "key"),
    ("BPCNAM_0", "customer_name", "str"),
    ("BPCGRU_0", "customer_group_code", "str"),
    ("CUR_0", "currency_code", "str"),
    ("PTE_0", "payment_term_code", "str"),
    ("BPCSNC_0", "credit_limit_amount", "num"),
    ("OSTCTL_0", "credit_control_code", "int"),
    ("ACCCOD_0", "accounting_code", "str"),
    ("REP_0", "primary_rep_code", "key"),
    ("REP_1", "secondary_rep_code", "key"),
    ("CREDAT_0", "created_date", "sdate"),
    ("UPDDAT_0", "updated_date", "sdate"),
    ("UPDTICK_0", "update_tick", "int"),
])

t("sage_x3", "BPSUPPLIER", "One row per supplier account.", [
    ("BPSNUM_0", "supplier_code", "key"),
    ("BPSNAM_0", "supplier_name", "str"),
    ("CUR_0", "currency_code", "str"),
    ("PTE_0", "payment_term_code", "str"),
    ("LTI_0", "lead_time_days", "int"),
    ("ACCCOD_0", "accounting_code", "str"),
    ("UPDTICK_0", "update_tick", "int"),
])

t("sage_x3", "BPADDRESS", "One row per business partner and address code.", [
    ("BPATYP_0", "partner_type_code", "int"),
    ("BPANUM_0", "partner_code", "key"),
    ("BPAADD_0", "address_code", "key"),
    ("BPADES_0", "address_description", "str"),
    ("ADDLIG_0", "address_line_1", "str"),
    ("ADDLIG_1", "address_line_2", "str"),
    ("CTY_0", "city", "str"),
    ("SAT_0", "state_province", "str"),
    ("POSCOD_0", "postal_code", "str"),
    ("CRY_0", "country_code", "str"),
    ("TEL_0", "phone", "str"),
])

t("sage_x3", "ITMMASTER", "One row per item.", [
    ("ITMREF_0", "item_code", "key"),
    ("ITMDES1_0", "item_description", "str"),
    ("ITMDES2_0", "item_description_2", "str"),
    ("TCLCOD_0", "item_category_code", "str"),
    ("TSICOD_0", "statistical_group_1", "str"),
    ("TSICOD_1", "statistical_group_2", "str"),
    ("TSICOD_2", "statistical_group_3", "str"),
    ("STU_0", "stock_unit", "str"),
    ("ITMSTA_0", "item_status_code", "int"),
    ("BASPRI_0", "base_sales_price", "num"),
    ("PURBASPRI_0", "base_purchase_price", "num"),
    ("EANCOD_0", "ean_code", "str"),
    ("ITMWEI_0", "item_weight", "num"),
    ("CREDAT_0", "created_date", "sdate"),
    ("UPDDAT_0", "updated_date", "sdate"),
    ("CREUSR_0", "created_by", "str"),
    ("UPDTICK_0", "update_tick", "int"),
], menus=[("item_status_code", 20, "item_status")])

t("sage_x3", "ITMFACILIT", "One row per item and site.", [
    ("ITMREF_0", "item_code", "key"),
    ("STOFCY_0", "site_code", "key"),
    ("REOMODE_0", "reorder_mode_code", "int"),
    ("SAFSTO_0", "safety_stock_qty", "num"),
    ("REOMINQTY_0", "reorder_min_qty", "num"),
    ("REOMAXQTY_0", "reorder_max_qty", "num"),
    ("LTISUP_0", "supplier_lead_time_days", "int"),
    ("ABCCLS_0", "abc_class", "str"),
    ("UPDTICK_0", "update_tick", "int"),
], menus=[("reorder_mode_code", 861, "reorder_mode")])

t("sage_x3", "SORDER", "One row per sales order header.", [
    ("SOHNUM_0", "sales_order_number", "key"),
    ("SALFCY_0", "sales_site_code", "key"),
    ("STOFCY_0", "shipping_site_code", "key"),
    ("BPCORD_0", "ordering_customer_code", "key"),
    ("BPCINV_0", "invoicing_customer_code", "key"),
    ("ORDDAT_0", "order_date", "sdate"),
    ("SHIDAT_0", "shipment_date", "sdate"),
    ("CUR_0", "currency_code", "str"),
    ("ORDSTA_0", "order_status_code", "int"),
    ("REP_0", "primary_rep_code", "key"),
    ("REP_1", "secondary_rep_code", "key"),
    ("TOTLINAMT_0", "order_total_amount", "num"),
    ("ORDINVSTA_0", "invoicing_status_code", "int"),
    ("CREUSR_0", "created_by", "str"),
    ("CREDAT_0", "created_date", "sdate"),
    ("UPDDAT_0", "updated_date", "sdate"),
    ("UPDTICK_0", "update_tick", "int"),
], menus=[("order_status_code", 415, "order_status")])

t("sage_x3", "SORDERQ", "One row per sales order line (quantity side).", [
    ("SOHNUM_0", "sales_order_number", "key"),
    ("SOPLIN_0", "sales_order_line_number", "int"),
    ("SOQSEQ_0", "sales_order_line_sequence", "int"),
    ("ITMREF_0", "item_code", "key"),
    ("STOFCY_0", "shipping_site_code", "key"),
    ("QTY_0", "ordered_qty", "num"),
    ("DEMDLVDAT_0", "requested_delivery_date", "sdate"),
    ("SHTQTY_0", "shipped_qty", "num"),
    ("UOM_0", "unit_of_measure", "str"),
    ("UPDTICK_0", "update_tick", "int"),
])

t("sage_x3", "SORDERP", "One row per sales order line (price side).", [
    ("SOHNUM_0", "sales_order_number", "key"),
    ("SOPLIN_0", "sales_order_line_number", "int"),
    ("SOPSEQ_0", "sales_order_line_sequence", "int"),
    ("ITMREF_0", "item_code", "key"),
    ("ITMDES1_0", "item_description_at_order", "str"),
    ("GROPRI_0", "gross_unit_price", "num"),
    ("NETPRI_0", "net_unit_price", "num"),
    ("DISCRGVAL1_0", "discount_amount", "num"),
    ("AMTNOTLIN_0", "line_net_amount", "num"),
    ("VAT1_0", "tax_code", "str"),
    ("UPDTICK_0", "update_tick", "int"),
])

t("sage_x3", "SINVOICEV", "One row per sales invoice header.", [
    ("NUM_0", "invoice_number", "key"),
    ("SIVTYP_0", "invoice_type_code", "str"),
    ("INVDAT_0", "invoice_date", "sdate"),
    ("BPR_0", "customer_code", "key"),
    ("SALFCY_0", "sales_site_code", "key"),
    ("CUR_0", "currency_code", "str"),
    ("AMTNOTLIN_0", "invoice_net_amount", "num"),
    ("AMTTAXLIN_0", "invoice_tax_amount", "num"),
    ("AMTATILIN_0", "invoice_gross_amount", "num"),
    ("INVSTA_0", "invoice_status_code", "int"),
    ("PAYDAT_0", "payment_date", "sdate"),
    ("ACCDAT_0", "accounting_date", "sdate"),
    ("UPDTICK_0", "update_tick", "int"),
])

t("sage_x3", "SINVOICED", "One row per sales invoice line.", [
    ("NUM_0", "invoice_number", "key"),
    ("SIDLIN_0", "invoice_line_number", "int"),
    ("ITMREF_0", "item_code", "key"),
    ("ITMDES1_0", "item_description_at_invoice", "str"),
    ("QTY_0", "invoiced_qty", "num"),
    ("NETPRI_0", "net_unit_price", "num"),
    ("AMTNOTLIN_0", "line_net_amount", "num"),
    ("SOHNUM_0", "sales_order_number", "key"),
    ("SOPLIN_0", "sales_order_line_number", "int"),
    ("STOFCY_0", "shipping_site_code", "key"),
])

t("sage_x3", "STOCK", "One row per item, site, lot and location.", [
    ("STOFCY_0", "site_code", "key"),
    ("ITMREF_0", "item_code", "key"),
    ("LOT_0", "lot_code", "key"),
    ("LOC_0", "location_code", "key"),
    ("QTYSTU_0", "on_hand_qty", "num"),
    ("STA_0", "stock_status", "str"),
    ("OWNER_0", "owner_code", "str"),
    ("UPDTICK_0", "update_tick", "int"),
])

t("sage_x3", "STOJOU", "One row per stock movement (STOJOU.ROWID).", [
    ("ROWID", "stock_movement_id", "int"),
    ("ITMREF_0", "item_code", "key"),
    ("STOFCY_0", "site_code", "key"),
    ("IPTDAT_0", "movement_date", "sdate"),
    ("TRSTYP_0", "movement_type_code", "int"),
    ("QTYSTU_0", "movement_qty", "num"),
    ("VCRNUM_0", "document_number", "key"),
    ("VCRTYP_0", "document_type", "str"),
    ("LOT_0", "lot_code", "key"),
    ("CREUSR_0", "created_by", "str"),
    ("UPDTICK_0", "update_tick", "int"),
], menus=[("movement_type_code", 700, "movement_type")])

t("sage_x3", "PORDER", "One row per purchase order header.", [
    ("POHNUM_0", "purchase_order_number", "key"),
    ("POHFCY_0", "purchase_site_code", "key"),
    ("BPSNUM_0", "supplier_code", "key"),
    ("ORDDAT_0", "order_date", "sdate"),
    ("ORDSTA_0", "order_status_code", "int"),
    ("CUR_0", "currency_code", "str"),
    ("CREUSR_0", "created_by", "str"),
    ("UPDTICK_0", "update_tick", "int"),
], menus=[("order_status_code", 415, "order_status")])

t("sage_x3", "PORDERQ", "One row per purchase order line.", [
    ("POHNUM_0", "purchase_order_number", "key"),
    ("POPLIN_0", "purchase_order_line_number", "int"),
    ("POQSEQ_0", "purchase_order_line_sequence", "int"),
    ("ITMREF_0", "item_code", "key"),
    ("POHFCY_0", "purchase_site_code", "key"),
    ("QTYUOM_0", "ordered_qty", "num"),
    ("EXTRCPDAT_0", "expected_receipt_date", "sdate"),
    ("RCPQTY_0", "received_qty", "num"),
    ("RCPDAT_0", "actual_receipt_date", "sdate"),
    ("NETPRI_0", "net_unit_price", "num"),
    ("UPDTICK_0", "update_tick", "int"),
])

t("sage_x3", "GACCENTRY", "One row per GL journal header.", [
    ("NUM_0", "journal_entry_number", "key"),
    ("TYP_0", "entry_type_code", "str"),
    ("JOU_0", "journal_code", "str"),
    ("CPY_0", "company_code", "key"),
    ("FCY_0", "site_code", "key"),
    ("ACCDAT_0", "accounting_date", "sdate"),
    ("CUR_0", "currency_code", "str"),
    ("DES_0", "description", "str"),
    ("VCRNUM_0", "source_document_number", "key"),
    ("STA_0", "entry_status_code", "int"),
    ("UPDTICK_0", "update_tick", "int"),
])

t("sage_x3", "GACCENTRYD", "One row per GL journal line.", [
    ("NUM_0", "journal_entry_number", "key"),
    ("LIN_0", "journal_line_number", "int"),
    ("ACC_0", "gl_account_code", "key"),
    ("SNS_0", "debit_credit_sign", "int"),
    ("AMTCUR_0", "amount_document_currency", "num"),
    ("AMTLOC_0", "amount_company_currency", "num"),
    ("BPR_0", "partner_code", "key"),
    ("CPY_0", "company_code", "key"),
    ("FCY_0", "site_code", "key"),
    ("DSP_0", "dimension_code", "str"),
    ("ACCDAT_0", "accounting_date", "sdate"),
])

t("sage_x3", "SRETURN", "One row per customer return header.", [
    ("SRHNUM_0", "return_number", "key"),
    ("SRHFCY_0", "site_code", "key"),
    ("BPCNUM_0", "customer_code", "key"),
    ("RTNDAT_0", "return_date", "sdate"),
    ("SOHNUM_0", "sales_order_number", "key"),
    ("SIVNUM_0", "invoice_number", "key"),
    ("RTNSTA_0", "return_status_code", "int"),
    ("RTNREN_0", "return_reason_code", "int"),
    ("CREUSR_0", "created_by", "str"),
    ("UPDTICK_0", "update_tick", "int"),
], menus=[("return_status_code", 740, "return_status"),
          ("return_reason_code", 720, "return_reason")])

t("sage_x3", "SRETURND", "One row per customer return line.", [
    ("SRHNUM_0", "return_number", "key"),
    ("SRDLIN_0", "return_line_number", "int"),
    ("ITMREF_0", "item_code", "key"),
    ("QTY_0", "returned_qty", "num"),
    ("NETPRI_0", "net_unit_price", "num"),
    ("AMTNOTLIN_0", "line_net_amount", "num"),
    ("SOHNUM_0", "sales_order_number", "key"),
    ("SOPLIN_0", "sales_order_line_number", "int"),
    ("STOFCY_0", "site_code", "key"),
    ("RTNREN_0", "return_reason_code", "int"),
], menus=[("return_reason_code", 720, "return_reason")])

t("sage_x3", "PRECEIPT", "One row per goods receipt header.", [
    ("PTHNUM_0", "receipt_number", "key"),
    ("PTHFCY_0", "receipt_site_code", "key"),
    ("BPSNUM_0", "supplier_code", "key"),
    ("POHNUM_0", "purchase_order_number", "key"),
    ("RCPDAT_0", "receipt_date", "sdate"),
    ("PTHTYP_0", "receipt_type_code", "int"),
    ("CREUSR_0", "received_by", "str"),
    ("UPDTICK_0", "update_tick", "int"),
])

t("sage_x3", "PRECEIPTD", "One row per goods receipt line.", [
    ("PTHNUM_0", "receipt_number", "key"),
    ("PTDLIN_0", "receipt_line_number", "int"),
    ("POHNUM_0", "purchase_order_number", "key"),
    ("POPLIN_0", "purchase_order_line_number", "int"),
    ("ITMREF_0", "item_code", "key"),
    ("PTHFCY_0", "receipt_site_code", "key"),
    ("QTYUOM_0", "received_qty", "num"),
    ("RCPDAT_0", "receipt_date", "sdate"),
])

t("sage_x3", "PINVOICE", "One row per supplier invoice header.", [
    ("NUM_0", "supplier_invoice_number", "key"),
    ("PIVTYP_0", "invoice_type_code", "str"),
    ("BPSNUM_0", "supplier_code", "key"),
    ("BPSINV_0", "supplier_document_number", "str"),
    ("INVDAT_0", "invoice_date", "sdate"),
    ("ACCDAT_0", "accounting_date", "sdate"),
    ("PIHFCY_0", "site_code", "key"),
    ("CUR_0", "currency_code", "str"),
    ("AMTNOTLIN_0", "net_amount", "num"),
    ("AMTTAXLIN_0", "tax_amount", "num"),
    ("AMTATILIN_0", "gross_amount", "num"),
    ("INVSTA_0", "invoice_status_code", "int"),
    ("UPDTICK_0", "update_tick", "int"),
])

t("sage_x3", "PINVOICED", "One row per supplier invoice line.", [
    ("NUM_0", "supplier_invoice_number", "key"),
    ("PIDLIN_0", "supplier_invoice_line_number", "int"),
    ("POHNUM_0", "purchase_order_number", "key"),
    ("POPLIN_0", "purchase_order_line_number", "int"),
    ("PTHNUM_0", "receipt_number", "key"),
    ("ITMREF_0", "item_code", "key"),
    ("QTY_0", "invoiced_qty", "num"),
    ("NETPRI_0", "invoiced_unit_price", "num"),
    ("AMTNOTLIN_0", "line_net_amount", "num"),
    ("PIHFCY_0", "site_code", "key"),
])

t("sage_x3", "STOCOUNT", "One row per inventory count session.", [
    ("SESNUM_0", "count_session_number", "key"),
    ("STOFCY_0", "site_code", "key"),
    ("CNTDAT_0", "count_date", "sdate"),
    ("CNTTYP_0", "count_type_code", "int"),
    ("SESSTA_0", "session_status_code", "int"),
    ("CREUSR_0", "counted_by", "str"),
    ("UPDTICK_0", "update_tick", "int"),
], menus=[("count_type_code", 730, "count_type"),
          ("session_status_code", 740, "session_status")])

t("sage_x3", "STOCOUNTD", "One row per counted stock position.", [
    ("SESNUM_0", "count_session_number", "key"),
    ("CNTLIN_0", "count_line_number", "int"),
    ("ITMREF_0", "item_code", "key"),
    ("STOFCY_0", "site_code", "key"),
    ("LOC_0", "location_code", "str"),
    ("LOT_0", "lot_code", "str"),
    ("QTYTHEO_0", "system_qty", "num"),
    ("QTYCNT_0", "counted_qty", "num"),
    ("CNTSTA_0", "count_line_status_code", "int"),
], menus=[("count_line_status_code", 740, "count_line_status")])

t("sage_x3", "REPRESENT", "One row per sales representative.", [
    ("REPNUM_0", "rep_code", "key"),
    ("REPNAM_0", "rep_name", "str"),
    ("FCY_0", "site_code", "key"),
    ("REPTYP_0", "rep_type_code", "int"),
    ("UPDTICK_0", "update_tick", "int"),
])

t("sage_x3", "APLSTD", "One row per local menu chapter, code and language.", [
    ("CHAPTER_0", "menu_chapter", "int"),
    ("CODE_0", "menu_code", "int"),
    ("LANNUM_0", "language_code", "str"),
    ("TEXTE_0", "menu_label", "str"),
])

t("sage_x3", "ATEXTRA", "One row per translated field value.", [
    ("CODFIC_0", "table_code", "str"),
    ("ZONE_0", "field_code", "str"),
    ("LANNUM_0", "language_code", "str"),
    ("IDENT1_0", "key_1", "key"),
    ("IDENT2_0", "key_2", "key"),
    ("TEXTE_0", "translated_text", "str"),
])

# --------------------------------- hubspot --------------------------------
t("hubspot", "company", "One row per HubSpot company.", [
    ("id", "company_id", "key"),
    ("name", "company_name", "str"),
    ("domain", "domain", "str"),
    ("industry", "industry", "str"),
    ("country", "country", "str"),
    ("numberofemployees", "employee_count", "hsnum"),
    ("annualrevenue", "annual_revenue", "hsnum"),
    ("hubspot_owner_id", "owner_id", "key"),
    ("createdate", "created_date", "date"),
    ("hs_lastmodifieddate", "last_modified_date", "date"),
    ("archived", "is_archived", "bool"),
])

t("hubspot", "contact", "One row per HubSpot contact.", [
    ("id", "contact_id", "key"),
    ("email", "email", "str"),
    ("firstname", "first_name", "str"),
    ("lastname", "last_name", "str"),
    ("jobtitle", "job_title", "str"),
    ("phone", "phone", "str"),
    ("lifecyclestage", "lifecycle_stage", "str"),
    ("hs_lead_status", "lead_status", "str"),
    ("hubspot_owner_id", "owner_id", "key"),
    ("associatedcompanyid", "company_id", "key"),
    ("createdate", "created_date", "date"),
    ("lastmodifieddate", "last_modified_date", "date"),
    ("archived", "is_archived", "bool"),
])

t("hubspot", "deal", "One row per HubSpot deal.", [
    ("id", "deal_id", "key"),
    ("dealname", "deal_name", "str"),
    ("amount", "deal_amount", "hsnum"),
    ("dealstage", "deal_stage_id", "str"),
    ("pipeline", "pipeline_id", "str"),
    ("closedate", "close_date", "date"),
    ("createdate", "created_date", "date"),
    ("hs_lastmodifieddate", "last_modified_date", "date"),
    ("hubspot_owner_id", "owner_id", "key"),
    ("dealtype", "deal_type", "str"),
    ("hs_is_closed_won", "is_closed_won", "bool"),
    ("hs_deal_stage_probability", "stage_probability", "hsnum"),
    ("erp_order_number", "erp_order_number_raw", "str"),
    ("associated_company_id", "company_id", "key"),
    ("archived", "is_archived", "bool"),
])

t("hubspot", "deal_stage_history", "One row per deal stage change.", [
    ("deal_id", "deal_id", "key"),
    ("stage", "deal_stage_id", "str"),
    ("changed_at", "changed_at_date", "date"),
    ("changed_by_owner_id", "changed_by_owner_id", "key"),
])

t("hubspot", "association", "One row per HubSpot object association.", [
    ("from_object_type", "from_object_type", "str"),
    ("from_id", "from_id", "key"),
    ("to_object_type", "to_object_type", "str"),
    ("to_id", "to_id", "key"),
    ("association_type", "association_type", "str"),
])

t("hubspot", "engagement", "One row per HubSpot engagement.", [
    ("id", "engagement_id", "key"),
    ("type", "engagement_type", "str"),
    ("created_at", "created_date", "date"),
    ("owner_id", "owner_id", "key"),
    ("associated_deal_id", "deal_id", "key"),
    ("associated_company_id", "company_id", "key"),
    ("body_preview", "body_preview", "str"),
])

t("hubspot", "owner", "One row per HubSpot owner.", [
    ("id", "owner_id", "key"),
    ("email", "email", "str"),
    ("first_name", "first_name", "str"),
    ("last_name", "last_name", "str"),
    ("user_id", "user_id", "key"),
    ("archived", "is_archived", "bool"),
    ("created_at", "created_date", "date"),
    ("updated_at", "updated_date", "date"),
])

t("hubspot", "pipeline_stage", "One row per pipeline and stage.", [
    ("pipeline_id", "pipeline_id", "key"),
    ("pipeline_label", "pipeline_label", "str"),
    ("stage_id", "deal_stage_id", "key"),
    ("stage_label", "stage_label", "str"),
    ("display_order", "display_order", "int"),
    ("is_closed", "is_closed", "bool"),
    ("is_closed_won", "is_closed_won", "bool"),
])

# ---------------------------------- paycom --------------------------------
t("paycom", "employee", "One row per Paycom employee.", [
    ("employee_code", "employee_code", "key"),
    ("ee_id", "employee_id", "key"),
    ("legal_first_name", "legal_first_name", "str"),
    ("legal_last_name", "legal_last_name", "str"),
    ("preferred_name", "preferred_name", "str"),
    ("work_email", "work_email", "str"),
    ("hire_date", "hire_date", "pdate"),
    ("rehire_date", "rehire_date", "pdate"),
    ("termination_date", "termination_date", "pdate"),
    ("employment_status", "employment_status", "str"),
    ("department_code", "department_code", "key"),
    ("department_desc", "department_name", "str"),
    ("location_code", "payroll_location_code", "key"),
    ("position_title", "position_title", "str"),
    ("pay_type", "pay_type", "str"),
    ("annual_salary", "annual_salary", "pnum"),
    ("hourly_rate", "hourly_rate", "pnum"),
    ("manager_ee_id", "manager_employee_id", "key"),
], extra=[
    ("full_name_normalized",
     "upper(nullif(trim(\"legal_first_name\"), '') || ' ' || nullif(trim(\"legal_last_name\"), ''))"),
])

t("paycom", "check", "One row per employee and pay period.", [
    ("check_id", "check_id", "key"),
    ("employee_code", "employee_code", "key"),
    ("check_date", "check_date", "pdate"),
    ("period_start", "period_start_date", "pdate"),
    ("period_end", "period_end_date", "pdate"),
    ("check_number", "check_number", "key"),
    ("gross_pay", "gross_pay_amount", "pnum"),
    ("net_pay", "net_pay_amount", "pnum"),
    ("check_type", "check_type", "str"),
    ("location_code", "payroll_location_code", "key"),
    ("department_code", "department_code", "key"),
], model="stg_paycom__check")

t("paycom", "earning_detail", "One row per check and earning code.", [
    ("check_id", "check_id", "key"),
    ("employee_code", "employee_code", "key"),
    ("earning_code", "earning_code", "key"),
    ("earning_desc", "earning_description", "str"),
    ("hours", "hours", "pnum"),
    ("amount", "earning_amount", "pnum"),
    ("labor_allocation_code", "labor_allocation_code", "key"),
])

t("paycom", "deduction_detail", "One row per check and deduction code.", [
    ("check_id", "check_id", "key"),
    ("employee_code", "employee_code", "key"),
    ("deduction_code", "deduction_code", "key"),
    ("ee_amount", "employee_amount", "pnum"),
    ("er_amount", "employer_amount", "pnum"),
])

t("paycom", "tax_detail", "One row per check and tax code.", [
    ("check_id", "check_id", "key"),
    ("employee_code", "employee_code", "key"),
    ("tax_code", "tax_code", "key"),
    ("ee_amount", "employee_amount", "pnum"),
    ("er_amount", "employer_amount", "pnum"),
])

t("paycom", "gl_mapping", "One row per payroll code and GL account.", [
    ("code_type", "code_type", "str"),
    ("code", "payroll_code", "key"),
    ("description", "code_description", "str"),
    ("gl_account", "gl_account_code", "key"),
])

# --------------------------------- netstock -------------------------------
t("netstock", "item_location", "One row per item and location.", [
    ("item_code", "item_code", "key"),
    ("location_code", "location_code", "key"),
    ("description", "item_description", "str"),
    ("abc_class", "abc_class", "str"),
    ("xyz_class", "xyz_class", "str"),
    ("policy", "replenishment_policy", "str"),
    ("lead_time_days", "lead_time_days", "int"),
    ("safety_stock_qty", "safety_stock_qty", "num"),
    ("reorder_point_qty", "reorder_point_qty", "num"),
    ("min_order_qty", "min_order_qty", "num"),
    ("supplier_code", "supplier_code", "key"),
    ("on_hand_qty", "on_hand_qty", "num"),
    ("on_order_qty", "on_order_qty", "num"),
    ("excess_value", "excess_value", "num"),
    ("stockout_risk", "stockout_risk", "str"),
    ("last_sync_at", "last_sync_date", "date"),
])

t("netstock", "forecast", "One row per item, location and forecast period.", [
    ("item_code", "item_code", "key"),
    ("location_code", "location_code", "key"),
    ("period_start", "period_start_date", "date"),
    ("period_type", "period_type", "str"),
    ("forecast_qty", "forecast_qty", "num"),
    ("forecast_method", "forecast_method", "str"),
    ("generated_at", "generated_date", "date"),
])

t("netstock", "forecast_accuracy", "One row per item, location and period.", [
    ("item_code", "item_code", "key"),
    ("location_code", "location_code", "key"),
    ("period_start", "period_start_date", "date"),
    ("forecast_qty", "forecast_qty", "num"),
    ("actual_qty", "actual_qty", "num"),
    ("abs_pct_error", "abs_pct_error", "num"),
])

t("netstock", "replenishment_recommendation", "One row per recommendation.", [
    ("recommendation_id", "recommendation_id", "key"),
    ("item_code", "item_code", "key"),
    ("location_code", "location_code", "key"),
    ("recommended_qty", "recommended_qty", "num"),
    ("recommended_order_date", "recommended_order_date", "date"),
    ("required_date", "required_date", "date"),
    ("supplier_code", "supplier_code", "key"),
    ("status", "status", "str"),
    ("erp_po_number", "erp_purchase_order_number", "key"),
    ("generated_at", "generated_date", "date"),
])

t("netstock", "supplier", "One row per Netstock supplier.", [
    ("supplier_code", "supplier_code", "key"),
    ("supplier_name", "supplier_name", "str"),
    ("lead_time_days", "lead_time_days", "int"),
    ("min_order_value", "min_order_value", "num"),
    ("source_system", "source_system", "str"),
])

# ---------------------------------- pangea --------------------------------
t("pangea", "shipment", "One row per shipment.", [
    ("shipment_id", "shipment_id", "key"),
    ("reference_number", "reference_number", "key"),
    ("customer_name", "customer_name", "str"),
    ("carrier_scac", "carrier_scac", "key"),
    ("service_level", "service_level", "str"),
    ("mode", "transport_mode", "str"),
    ("origin_site_code", "origin_site_code", "key"),
    ("dest_city", "destination_city", "str"),
    ("dest_state", "destination_state", "str"),
    ("dest_postal", "destination_postal_code", "str"),
    ("dest_country", "destination_country", "str"),
    ("ship_date", "ship_date", "date"),
    ("estimated_delivery_date", "carrier_promised_delivery_date", "date"),
    ("delivered_date", "delivered_date", "date"),
    ("status", "shipment_status", "str"),
    ("weight_lb", "weight_lb", "num"),
    ("piece_count", "piece_count", "int"),
    ("total_cost_usd", "header_cost_usd", "num"),
    ("created_at", "created_date", "date"),
])

t("pangea", "shipment_leg", "One row per shipment leg.", [
    ("shipment_id", "shipment_id", "key"),
    ("leg_seq", "leg_sequence", "int"),
    ("mode", "transport_mode", "str"),
    ("carrier_scac", "carrier_scac", "key"),
    ("origin", "origin", "str"),
    ("destination", "destination", "str"),
    ("depart_ts", "depart_date", "date"),
    ("arrive_ts", "arrive_date", "date"),
])

t("pangea", "tracking_event", "One row per shipment and event sequence.", [
    ("shipment_id", "shipment_id", "key"),
    ("event_seq", "event_sequence", "int"),
    ("event_code", "event_code", "key"),
    ("event_description", "event_description", "str"),
    ("event_ts", "event_at", "date"),
    ("event_location", "event_location", "str"),
])

t("pangea", "charge", "One row per shipment and charge code.", [
    ("shipment_id", "shipment_id", "key"),
    ("charge_code", "charge_code", "key"),
    ("amount_usd", "charge_amount_usd", "num"),
    ("currency", "currency_code", "str"),
])

t("pangea", "carrier", "One row per carrier.", [
    ("scac", "carrier_scac", "key"),
    ("carrier_name", "carrier_name", "str"),
    ("mode", "transport_mode", "str"),
])


HEADER = """\
-- Generated by scripts/generate_staging.py. Cleaning only: no business logic.
-- Grain: {grain}
"""


def model_name(schema, table):
    return f"stg_{schema}__{table.lower()}"


def render(schema, table, spec):
    name = spec["model"] or model_name(schema, table)
    lines = [HEADER.format(grain=spec["grain"])]
    lines.append("with source as (\n")
    lines.append(f"    select * from {{{{ source('{schema}', '{table}') }}}}\n")
    lines.append("),\n\n")
    lines.append("cleaned as (\n\n    select\n")
    sel = []
    for src, alias, kind in spec["cols"]:
        e = expr(src, kind)
        sel.append(f"        {e} as {alias}")
    for alias, sql in spec["extra"]:
        sel.append(f"        {sql} as {alias}")
    lines.append(",\n".join(sel) + "\n\n    from source\n\n)")

    if spec["menus"]:
        prev = "cleaned"
        for i, (int_alias, chapter, label_alias) in enumerate(spec["menus"]):
            step = f"decoded_{label_alias}"
            lines.append(",\n\n")
            lines.append(f"{step} as (\n\n    select\n")
            lines.append(f"        base.*,\n")
            lines.append(f"        menu.menu_label as {label_alias}\n\n")
            lines.append(f"    from {prev} as base\n")
            lines.append(
                "    left join {{ ref('stg_sage_x3__aplstd') }} as menu\n"
                f"        on menu.menu_chapter = {chapter}\n"
                f"        and menu.menu_code = base.{int_alias}\n"
                "        and menu.language_code = 'ENG'\n\n)"
            )
            prev = step
        lines.append(f"\n\nselect * from {prev}\n")
    else:
        lines.append("\n\nselect * from cleaned\n")
    return name, "".join(lines)


def main():
    written = []
    for (schema, table), spec in SPEC.items():
        name, sql = render(schema, table, spec)
        path = os.path.join(ROOT, "models", "staging", schema, f"{name}.sql")
        with open(path, "w") as fh:
            fh.write(sql)
        written.append(path)
    print(f"wrote {len(written)} staging models")


if __name__ == "__main__":
    main()
