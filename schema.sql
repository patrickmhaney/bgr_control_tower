-- Portable DDL for the five mock source schemas.
CREATE SCHEMA IF NOT EXISTS sage_x3;
CREATE SCHEMA IF NOT EXISTS hubspot;
CREATE SCHEMA IF NOT EXISTS paycom;
CREATE SCHEMA IF NOT EXISTS netstock;
CREATE SCHEMA IF NOT EXISTS pangea;

CREATE TABLE hubspot."association" (
    "from_object_type" varchar(255),
    "from_id" varchar(255),
    "to_object_type" varchar(255),
    "to_id" varchar(255),
    "association_type" varchar(255)
);

CREATE TABLE hubspot."company" (
    "id" varchar(255),
    "name" varchar(255),
    "domain" varchar(255),
    "industry" varchar(255),
    "country" varchar(255),
    "numberofemployees" varchar(255),
    "annualrevenue" varchar(255),
    "hubspot_owner_id" varchar(255),
    "createdate" date,
    "hs_lastmodifieddate" date,
    "archived" boolean
);

CREATE TABLE hubspot."contact" (
    "id" varchar(255),
    "email" varchar(255),
    "firstname" varchar(255),
    "lastname" varchar(255),
    "jobtitle" varchar(255),
    "phone" varchar(255),
    "lifecyclestage" varchar(255),
    "hs_lead_status" varchar(255),
    "hubspot_owner_id" varchar(255),
    "associatedcompanyid" varchar(255),
    "createdate" date,
    "lastmodifieddate" date,
    "archived" boolean
);

CREATE TABLE hubspot."deal" (
    "id" varchar(255),
    "dealname" varchar(255),
    "amount" varchar(255),
    "dealstage" varchar(255),
    "pipeline" varchar(255),
    "closedate" date,
    "createdate" date,
    "hs_lastmodifieddate" date,
    "hubspot_owner_id" varchar(255),
    "dealtype" varchar(255),
    "hs_is_closed_won" boolean,
    "hs_deal_stage_probability" varchar(255),
    "erp_order_number" varchar(255),
    "associated_company_id" varchar(255),
    "archived" boolean
);

CREATE TABLE hubspot."deal_stage_history" (
    "deal_id" varchar(255),
    "stage" varchar(255),
    "changed_at" date,
    "changed_by_owner_id" varchar(255)
);

CREATE TABLE hubspot."engagement" (
    "id" varchar(255),
    "type" varchar(255),
    "created_at" date,
    "owner_id" varchar(255),
    "associated_deal_id" varchar(255),
    "associated_company_id" varchar(255),
    "body_preview" varchar(255)
);

CREATE TABLE hubspot."owner" (
    "id" varchar(255),
    "email" varchar(255),
    "first_name" varchar(255),
    "last_name" varchar(255),
    "user_id" varchar(255),
    "archived" boolean,
    "created_at" date,
    "updated_at" date
);

CREATE TABLE hubspot."pipeline_stage" (
    "pipeline_id" varchar(255),
    "pipeline_label" varchar(255),
    "stage_id" varchar(255),
    "stage_label" varchar(255),
    "display_order" bigint,
    "is_closed" boolean,
    "is_closed_won" boolean
);

CREATE TABLE netstock."forecast" (
    "item_code" varchar(255),
    "location_code" varchar(255),
    "period_start" date,
    "period_type" varchar(255),
    "forecast_qty" numeric(18,4),
    "forecast_method" varchar(255),
    "generated_at" date
);

CREATE TABLE netstock."forecast_accuracy" (
    "item_code" varchar(255),
    "location_code" varchar(255),
    "period_start" date,
    "forecast_qty" numeric(18,4),
    "actual_qty" numeric(18,4),
    "abs_pct_error" numeric(18,4)
);

CREATE TABLE netstock."item_location" (
    "item_code" varchar(255),
    "location_code" varchar(255),
    "description" varchar(255),
    "abc_class" varchar(255),
    "xyz_class" varchar(255),
    "policy" varchar(255),
    "lead_time_days" bigint,
    "safety_stock_qty" numeric(18,4),
    "reorder_point_qty" numeric(18,4),
    "min_order_qty" numeric(18,4),
    "supplier_code" varchar(255),
    "on_hand_qty" numeric(18,4),
    "on_order_qty" numeric(18,4),
    "excess_value" numeric(18,4),
    "stockout_risk" varchar(255),
    "last_sync_at" date
);

CREATE TABLE netstock."replenishment_recommendation" (
    "recommendation_id" varchar(255),
    "item_code" varchar(255),
    "location_code" varchar(255),
    "recommended_qty" numeric(18,4),
    "recommended_order_date" date,
    "required_date" date,
    "supplier_code" varchar(255),
    "status" varchar(255),
    "erp_po_number" varchar(255),
    "generated_at" date
);

CREATE TABLE netstock."supplier" (
    "supplier_code" varchar(255),
    "supplier_name" varchar(255),
    "lead_time_days" bigint,
    "min_order_value" numeric(18,4),
    "source_system" varchar(255)
);

CREATE TABLE pangea."carrier" (
    "scac" varchar(255),
    "carrier_name" varchar(255),
    "mode" varchar(255)
);

CREATE TABLE pangea."charge" (
    "shipment_id" varchar(255),
    "charge_code" varchar(255),
    "amount_usd" numeric(18,4),
    "currency" varchar(255)
);

CREATE TABLE pangea."shipment" (
    "shipment_id" varchar(255),
    "reference_number" varchar(255),
    "customer_name" varchar(255),
    "carrier_scac" varchar(255),
    "service_level" varchar(255),
    "mode" varchar(255),
    "origin_site_code" varchar(255),
    "dest_city" varchar(255),
    "dest_state" varchar(255),
    "dest_postal" varchar(255),
    "dest_country" varchar(255),
    "ship_date" date,
    "estimated_delivery_date" date,
    "delivered_date" date,
    "status" varchar(255),
    "weight_lb" numeric(18,4),
    "piece_count" bigint,
    "total_cost_usd" numeric(18,4),
    "created_at" date
);

CREATE TABLE pangea."shipment_leg" (
    "shipment_id" varchar(255),
    "leg_seq" bigint,
    "mode" varchar(255),
    "carrier_scac" varchar(255),
    "origin" varchar(255),
    "destination" varchar(255),
    "depart_ts" date,
    "arrive_ts" date
);

CREATE TABLE pangea."tracking_event" (
    "shipment_id" varchar(255),
    "event_seq" bigint,
    "event_code" varchar(255),
    "event_description" varchar(255),
    "event_ts" date,
    "event_location" varchar(255)
);

CREATE TABLE paycom."check" (
    "check_id" varchar(255),
    "employee_code" varchar(255),
    "check_date" varchar(255),
    "period_start" varchar(255),
    "period_end" varchar(255),
    "check_number" varchar(255),
    "gross_pay" varchar(255),
    "net_pay" varchar(255),
    "check_type" varchar(255),
    "location_code" varchar(255),
    "department_code" varchar(255)
);

CREATE TABLE paycom."deduction_detail" (
    "check_id" varchar(255),
    "employee_code" varchar(255),
    "deduction_code" varchar(255),
    "ee_amount" varchar(255),
    "er_amount" varchar(255)
);

CREATE TABLE paycom."earning_detail" (
    "check_id" varchar(255),
    "employee_code" varchar(255),
    "earning_code" varchar(255),
    "earning_desc" varchar(255),
    "hours" varchar(255),
    "amount" varchar(255),
    "labor_allocation_code" varchar(255)
);

CREATE TABLE paycom."employee" (
    "employee_code" varchar(255),
    "ee_id" varchar(255),
    "legal_first_name" varchar(255),
    "legal_last_name" varchar(255),
    "preferred_name" varchar(255),
    "work_email" varchar(255),
    "hire_date" varchar(255),
    "rehire_date" varchar(255),
    "termination_date" varchar(255),
    "employment_status" varchar(255),
    "department_code" varchar(255),
    "department_desc" varchar(255),
    "location_code" varchar(255),
    "position_title" varchar(255),
    "pay_type" varchar(255),
    "annual_salary" varchar(255),
    "hourly_rate" varchar(255),
    "ssn_last4" varchar(255),
    "manager_ee_id" varchar(255)
);

CREATE TABLE paycom."gl_mapping" (
    "code_type" varchar(255),
    "code" varchar(255),
    "description" varchar(255),
    "gl_account" varchar(255)
);

CREATE TABLE paycom."tax_detail" (
    "check_id" varchar(255),
    "employee_code" varchar(255),
    "tax_code" varchar(255),
    "ee_amount" varchar(255),
    "er_amount" varchar(255)
);

CREATE TABLE sage_x3."APLSTD" (
    "CHAPTER_0" bigint,
    "CODE_0" bigint,
    "LANNUM_0" varchar(255),
    "TEXTE_0" varchar(255)
);

CREATE TABLE sage_x3."ATEXTRA" (
    "CODFIC_0" varchar(255),
    "ZONE_0" varchar(255),
    "LANNUM_0" varchar(255),
    "IDENT1_0" varchar(255),
    "IDENT2_0" varchar(255),
    "TEXTE_0" varchar(255)
);

CREATE TABLE sage_x3."BPADDRESS" (
    "BPATYP_0" bigint,
    "BPANUM_0" varchar(255),
    "BPAADD_0" varchar(255),
    "BPADES_0" varchar(255),
    "ADDLIG_0" varchar(255),
    "ADDLIG_1" varchar(255),
    "CTY_0" varchar(255),
    "SAT_0" varchar(255),
    "POSCOD_0" varchar(255),
    "CRY_0" varchar(255),
    "TEL_0" varchar(255)
);

CREATE TABLE sage_x3."BPARTNER" (
    "BPRNUM_0" varchar(255),
    "BPRNAM_0" varchar(255),
    "BPRNAM_1" varchar(255),
    "BPCFLG_0" bigint,
    "BPSFLG_0" bigint,
    "CRY_0" varchar(255),
    "CUR_0" varchar(255),
    "BPRLOG_0" bigint,
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."BPCUSTOMER" (
    "BPCNUM_0" varchar(255),
    "BPCNAM_0" varchar(255),
    "BPCGRU_0" varchar(255),
    "CUR_0" varchar(255),
    "PTE_0" varchar(255),
    "BPCSNC_0" numeric(18,4),
    "OSTCTL_0" bigint,
    "ACCCOD_0" varchar(255),
    "REP_0" varchar(255),
    "REP_1" varchar(255),
    "CREDAT_0" date,
    "UPDDAT_0" date,
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."BPSUPPLIER" (
    "BPSNUM_0" varchar(255),
    "BPSNAM_0" varchar(255),
    "CUR_0" varchar(255),
    "PTE_0" varchar(255),
    "LTI_0" bigint,
    "ACCCOD_0" varchar(255),
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."COMPANY" (
    "CPY_0" varchar(255),
    "CPYNAM_0" varchar(255),
    "CRY_0" varchar(255),
    "LEG_0" varchar(255),
    "CPYLOG_0" bigint
);

CREATE TABLE sage_x3."FACILITY" (
    "FCY_0" varchar(255),
    "FCYSHO_0" varchar(255),
    "FCYNAM_0" varchar(255),
    "LEGCPY_0" varchar(255),
    "CRY_0" varchar(255),
    "CTY_0" varchar(255),
    "SAT_0" varchar(255),
    "FCYSTO_0" bigint,
    "FCYSAL_0" bigint,
    "FCYPUR_0" bigint
);

CREATE TABLE sage_x3."GACCENTRY" (
    "NUM_0" varchar(255),
    "TYP_0" varchar(255),
    "JOU_0" varchar(255),
    "CPY_0" varchar(255),
    "FCY_0" varchar(255),
    "ACCDAT_0" date,
    "CUR_0" varchar(255),
    "DES_0" varchar(255),
    "VCRNUM_0" varchar(255),
    "STA_0" bigint,
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."GACCENTRYD" (
    "NUM_0" varchar(255),
    "LIN_0" bigint,
    "ACC_0" varchar(255),
    "SNS_0" bigint,
    "AMTCUR_0" numeric(18,4),
    "AMTLOC_0" numeric(18,4),
    "BPR_0" varchar(255),
    "CPY_0" varchar(255),
    "FCY_0" varchar(255),
    "DSP_0" varchar(255),
    "ACCDAT_0" date
);

CREATE TABLE sage_x3."ITMFACILIT" (
    "ITMREF_0" varchar(255),
    "STOFCY_0" varchar(255),
    "REOMODE_0" bigint,
    "SAFSTO_0" numeric(18,4),
    "REOMINQTY_0" numeric(18,4),
    "REOMAXQTY_0" numeric(18,4),
    "LTISUP_0" bigint,
    "ABCCLS_0" varchar(255),
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."ITMMASTER" (
    "ITMREF_0" varchar(255),
    "ITMDES1_0" varchar(255),
    "ITMDES2_0" varchar(255),
    "TCLCOD_0" varchar(255),
    "TSICOD_0" varchar(255),
    "TSICOD_1" varchar(255),
    "TSICOD_2" varchar(255),
    "STU_0" varchar(255),
    "ITMSTA_0" bigint,
    "BASPRI_0" numeric(18,4),
    "PURBASPRI_0" numeric(18,4),
    "EANCOD_0" varchar(255),
    "ITMWEI_0" numeric(18,4),
    "CREDAT_0" date,
    "UPDDAT_0" date,
    "CREUSR_0" varchar(255),
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."PINVOICE" (
    "NUM_0" varchar(255),
    "PIVTYP_0" varchar(255),
    "BPSNUM_0" varchar(255),
    "BPSINV_0" varchar(255),
    "INVDAT_0" date,
    "ACCDAT_0" date,
    "PIHFCY_0" varchar(255),
    "CUR_0" varchar(255),
    "AMTNOTLIN_0" numeric(18,4),
    "AMTTAXLIN_0" numeric(18,4),
    "AMTATILIN_0" numeric(18,4),
    "INVSTA_0" bigint,
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."PINVOICED" (
    "NUM_0" varchar(255),
    "PIDLIN_0" bigint,
    "POHNUM_0" varchar(255),
    "POPLIN_0" bigint,
    "PTHNUM_0" varchar(255),
    "ITMREF_0" varchar(255),
    "QTY_0" numeric(18,4),
    "NETPRI_0" numeric(18,4),
    "AMTNOTLIN_0" numeric(18,4),
    "PIHFCY_0" varchar(255)
);

CREATE TABLE sage_x3."PORDER" (
    "POHNUM_0" varchar(255),
    "POHFCY_0" varchar(255),
    "BPSNUM_0" varchar(255),
    "ORDDAT_0" date,
    "ORDSTA_0" bigint,
    "CUR_0" varchar(255),
    "CREUSR_0" varchar(255),
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."PORDERQ" (
    "POHNUM_0" varchar(255),
    "POPLIN_0" bigint,
    "POQSEQ_0" bigint,
    "ITMREF_0" varchar(255),
    "POHFCY_0" varchar(255),
    "QTYUOM_0" numeric(18,4),
    "EXTRCPDAT_0" date,
    "RCPQTY_0" numeric(18,4),
    "RCPDAT_0" date,
    "NETPRI_0" numeric(18,4),
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."PRECEIPT" (
    "PTHNUM_0" varchar(255),
    "PTHFCY_0" varchar(255),
    "BPSNUM_0" varchar(255),
    "POHNUM_0" varchar(255),
    "RCPDAT_0" date,
    "PTHTYP_0" bigint,
    "CREUSR_0" varchar(255),
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."PRECEIPTD" (
    "PTHNUM_0" varchar(255),
    "PTDLIN_0" bigint,
    "POHNUM_0" varchar(255),
    "POPLIN_0" bigint,
    "ITMREF_0" varchar(255),
    "PTHFCY_0" varchar(255),
    "QTYUOM_0" numeric(18,4),
    "RCPDAT_0" date
);

CREATE TABLE sage_x3."REPRESENT" (
    "REPNUM_0" varchar(255),
    "REPNAM_0" varchar(255),
    "FCY_0" varchar(255),
    "REPTYP_0" bigint,
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."SINVOICED" (
    "NUM_0" varchar(255),
    "SIDLIN_0" bigint,
    "ITMREF_0" varchar(255),
    "ITMDES1_0" varchar(255),
    "QTY_0" numeric(18,4),
    "NETPRI_0" numeric(18,4),
    "AMTNOTLIN_0" numeric(18,4),
    "SOHNUM_0" varchar(255),
    "SOPLIN_0" bigint,
    "STOFCY_0" varchar(255)
);

CREATE TABLE sage_x3."SINVOICEV" (
    "NUM_0" varchar(255),
    "SIVTYP_0" varchar(255),
    "INVDAT_0" date,
    "BPR_0" varchar(255),
    "SALFCY_0" varchar(255),
    "CUR_0" varchar(255),
    "AMTNOTLIN_0" numeric(18,4),
    "AMTTAXLIN_0" numeric(18,4),
    "AMTATILIN_0" numeric(18,4),
    "INVSTA_0" bigint,
    "PAYDAT_0" date,
    "ACCDAT_0" date,
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."SORDER" (
    "SOHNUM_0" varchar(255),
    "SALFCY_0" varchar(255),
    "STOFCY_0" varchar(255),
    "BPCORD_0" varchar(255),
    "BPCINV_0" varchar(255),
    "ORDDAT_0" date,
    "SHIDAT_0" date,
    "CUR_0" varchar(255),
    "ORDSTA_0" bigint,
    "REP_0" varchar(255),
    "REP_1" varchar(255),
    "TOTLINAMT_0" numeric(18,4),
    "ORDINVSTA_0" bigint,
    "CREUSR_0" varchar(255),
    "CREDAT_0" date,
    "UPDDAT_0" date,
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."SORDERP" (
    "SOHNUM_0" varchar(255),
    "SOPLIN_0" bigint,
    "SOPSEQ_0" bigint,
    "ITMREF_0" varchar(255),
    "ITMDES1_0" varchar(255),
    "GROPRI_0" numeric(18,4),
    "NETPRI_0" numeric(18,4),
    "DISCRGVAL1_0" numeric(18,4),
    "AMTNOTLIN_0" numeric(18,4),
    "VAT1_0" varchar(255),
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."SORDERQ" (
    "SOHNUM_0" varchar(255),
    "SOPLIN_0" bigint,
    "SOQSEQ_0" bigint,
    "ITMREF_0" varchar(255),
    "STOFCY_0" varchar(255),
    "QTY_0" numeric(18,4),
    "DEMDLVDAT_0" date,
    "SHTQTY_0" numeric(18,4),
    "UOM_0" varchar(255),
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."SRETURN" (
    "SRHNUM_0" varchar(255),
    "SRHFCY_0" varchar(255),
    "BPCNUM_0" varchar(255),
    "RTNDAT_0" date,
    "SOHNUM_0" varchar(255),
    "SIVNUM_0" varchar(255),
    "RTNSTA_0" bigint,
    "RTNREN_0" bigint,
    "CREUSR_0" varchar(255),
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."SRETURND" (
    "SRHNUM_0" varchar(255),
    "SRDLIN_0" bigint,
    "ITMREF_0" varchar(255),
    "QTY_0" numeric(18,4),
    "NETPRI_0" numeric(18,4),
    "AMTNOTLIN_0" numeric(18,4),
    "SOHNUM_0" varchar(255),
    "SOPLIN_0" bigint,
    "STOFCY_0" varchar(255),
    "RTNREN_0" bigint
);

CREATE TABLE sage_x3."STOCK" (
    "STOFCY_0" varchar(255),
    "ITMREF_0" varchar(255),
    "LOT_0" varchar(255),
    "LOC_0" varchar(255),
    "QTYSTU_0" numeric(18,4),
    "STA_0" varchar(255),
    "OWNER_0" varchar(255),
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."STOCOUNT" (
    "SESNUM_0" varchar(255),
    "STOFCY_0" varchar(255),
    "CNTDAT_0" date,
    "CNTTYP_0" bigint,
    "SESSTA_0" bigint,
    "CREUSR_0" varchar(255),
    "UPDTICK_0" bigint
);

CREATE TABLE sage_x3."STOCOUNTD" (
    "SESNUM_0" varchar(255),
    "CNTLIN_0" bigint,
    "ITMREF_0" varchar(255),
    "STOFCY_0" varchar(255),
    "LOC_0" varchar(255),
    "LOT_0" varchar(255),
    "QTYTHEO_0" numeric(18,4),
    "QTYCNT_0" numeric(18,4),
    "CNTSTA_0" bigint
);

CREATE TABLE sage_x3."STOJOU" (
    "ROWID" bigint,
    "ITMREF_0" varchar(255),
    "STOFCY_0" varchar(255),
    "IPTDAT_0" date,
    "TRSTYP_0" bigint,
    "QTYSTU_0" numeric(18,4),
    "VCRNUM_0" varchar(255),
    "VCRTYP_0" varchar(255),
    "LOT_0" varchar(255),
    "CREUSR_0" varchar(255),
    "UPDTICK_0" bigint
);
