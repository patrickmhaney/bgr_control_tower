# Control Tower Atlas

Seventeen diagrams of the pipeline, each with the one thing worth looking at. The Mermaid source is read out of `docs/data_model.md` and `docs/ingestion.md`, so this page cannot drift from the repository.

**5** source systems | **233,150** rows ingested | **46** extraction resources | **80** dbt models | **207** tests, 4 warnings | **7** metrics live, 3 blocked

## Contents

- [§1 Getting the data out](#s1)
- [§2 The five source systems](#s2)
- [§3 Where the systems meet](#s3)
- [§4 The model the dashboards read](#s4)
- [§5 How one becomes the other](#s5)

<a id="s1"></a>

## §1 Getting the data out

Five systems, five different problems. The extraction layer is real code; only the five clients that talk to the source systems are stood in for. Everything here was measured by building it, not by reasoning about it.

### Fig 1.1 — The seam

*Five files stand between the pipeline and five real source systems. They are the only files that change to go live.*

```mermaid
flowchart TB
    subgraph SEAM["ingestion/simulators/ &mdash; replaced to go live"]
        direction LR
        a1["erp_database.py<br/><small>&rarr; pyodbc / oracledb<br/>on a read replica</small>"]
        a2["hubspot_api.py<br/><small>&rarr; HubSpot REST v3/v4<br/>private-app token</small>"]
        a3["paycom_sftp.py<br/><small>&rarr; paramiko on the<br/>real SFTP drop</small>"]
        a4["netstock_api.py<br/><small>&rarr; vendor API<br/>unconfirmed</small>"]
        a5["pangea_api.py<br/><small>&rarr; vendor API<br/>product unidentified</small>"]
    end

    subgraph KEEP["everything above the seam &mdash; unchanged"]
        direction TB
        c2["ingestion/sources.py<br/><small>46 dlt resources, watermarks, dispositions</small>"]
        c4["ingestion/pipeline.py<br/><small>landing archive + projection to raw</small>"]
        c5["80 dbt models<br/><small>staging &rarr; intermediate &rarr; core &rarr; metrics</small>"]
        c2 --> c4 --> c5
    end

    spec["ingestion/config.py<br/><small>46 table specs, 6 strategies</small>"]
    contract["ingestion/schema_contract.json<br/><small>46 tables, 422 columns, pinned</small>"]

    a1 --> c2
    a2 --> c2
    a3 --> c2
    a4 --> c2
    a5 --> c2
    spec -->|"which strategy,<br/>which key, which window"| c2
    contract -->|"type hints in,<br/>drift check out"| c2
```

**What to look at.** Everything below the seam is written against rows. A row from a real ERP looks exactly like a row from this one, which is why the 46 extraction specs, the watermark logic and all 80 dbt models are already production code.

### Fig 1.2 — Two stages, not one

*Extraction lands an append-only Parquet archive; a pure-SQL projection builds the raw schemas from it.*

```mermaid
flowchart LR
    sys(["five source systems"])
    dlt["dlt extract<br/><small>46 resources</small>"]
    land[("landing/<br/><small>&lt;source&gt;/&lt;table&gt;/load_date=YYYY-MM-DD/</small><br/><small><b>append-only &middot; nothing is ever deleted</b></small>")]
    proj{{"project_landing_to_raw()<br/><small>pure SQL &middot; no source access</small>"}}
    raw[("raw.duckdb<br/><small>5 schemas &middot; 46 tables &middot; 233,150 rows</small>")]
    dbt["dbt sources"]

    sys -->|"read once,<br/>per strategy"| dlt
    dlt -->|"one Parquet file<br/>per table per run"| land
    land -->|"replace: newest load package only<br/>merge: latest row per primary key"| proj
    proj --> raw
    raw --> dbt

    land -.->|"<b>replay</b><br/>rebuild without<br/>touching a source"| proj
    land -.->|"<b>audit</b><br/>what did the ERP<br/>return on the 3rd?"| land
```

**What to look at.** Loading straight into the warehouse would have been half the code. The second stage buys replay — rebuild without touching a source, which matters most for Paycom, where an export is gone once the next one overwrites it.

### Fig 1.3 — How the ERP gets read, and what it loses

*19 of 22 Sage X3 tables carry no modification date, so line tables are windowed through their parent's business date.*

```mermaid
flowchart LR
    subgraph SRC["what the ERP offers"]
        hdr["SORDER<br/><small>ORDDAT_0 &mdash; a <b>business</b> date<br/>UPDDAT_0 &mdash; a DATE, day-grain</small>"]
        lineq["SORDERQ<br/><small>11,575 lines<br/><b>no date column</b></small>"]
        linep["SORDERP<br/><small>11,575 lines<br/><b>no date column</b></small>"]
        tick["UPDTICK_0<br/><small>on 14 tables</small>"]
    end

    wm["watermark<br/><small>high-water mark<br/>minus 90-day lookback</small>"]
    ex["extract"]

    wm -->|"since = date"| ex
    hdr -->|"WHERE ORDDAT_0 &gt;= since"| ex
    lineq -->|"WHERE EXISTS parent<br/>in the same window"| ex
    linep -->|"WHERE EXISTS parent<br/>in the same window"| ex
    tick -.->|"<b>NOT a watermark.</b><br/>per-row lock counter,<br/>not a sequence"| ex

    ex --> good["caught<br/><small>anything on an order<br/>raised inside the window</small>"]
    ex --> lost["<b>missed forever</b><br/><small>a line amended today on an<br/>order raised 2 years ago</small>"]

    lost -.->|"the real fix"| cdc["SQL Server<br/>Change Tracking / CDC<br/><small>an infrastructure request</small>"]
```

**What to look at.** UPDTICK_0 looks like a change signal and is not: it is a per-row lock counter, not a sequence. The trap is on the right — a line amended today on an order raised two years ago falls outside any window keyed on the order date.

### Fig 1.4 — What can be read incrementally

*A second run reads 46% of the rows. Two of the five sources read everything, every time.*

```mermaid
flowchart TB
    subgraph CAN["can be read incrementally"]
        s1["<b>sage_x3</b> &middot; 22 tables<br/><small>3 modified-date &middot; 9 header-window<br/>10 full refresh</small>"]
        s2["<b>hubspot</b> &middot; 8 tables<br/><small>4 API cursor &middot; 4 full refresh</small>"]
        s3["<b>pangea</b> &middot; 5 tables<br/><small>1 API cursor &middot; 3 header-window<br/>1 full refresh</small>"]
    end
    subgraph CANNOT["cannot &mdash; and one of them should not"]
        s4["<b>paycom</b> &middot; 6 tables<br/><small>file drop &middot; <b>no change signal exists</b></small>"]
        s5["<b>netstock</b> &middot; 5 tables<br/><small>snapshot &middot; regenerated wholesale<br/><b>incremental would be WRONG</b></small>"]
    end

    s1 -->|"79,374 &rarr; 12,233<br/>85% saved"| out[("second run<br/>125,336 of 233,150 rows<br/><small>46% saved overall</small>")]
    s2 -->|"11,291 &rarr; 7,531<br/>33% saved"| out
    s3 -->|"41,712 &rarr; 4,799<br/>88% saved"| out
    s4 -->|"66,680 &rarr; 66,680<br/>0%"| out
    s5 -->|"34,093 &rarr; 34,093<br/>0%"| out
```

**What to look at.** Paycom has no change signal of any kind and never will. Netstock is different: it regenerates wholesale, so an incremental read would be actively wrong — a row that drops out of the recomputed set would persist in the warehouse forever.

### Fig 1.5 — How 26 rows disappeared

*Offset pagination over a non-unique sort key lost 26 rows and duplicated 26 others — and the row count never changed.*

```mermaid
sequenceDiagram
    autonumber
    participant E as extractor
    participant A as HubSpot API
    Note over E,A: 3,606 rows sorted by deal_id, which has only 850 distinct values
    E->>A: page 1 : ORDER BY deal_id LIMIT 100 OFFSET 0
    A-->>E: 100 rows. Ties on deal_id come back in whatever order the engine picked.
    E->>A: page 2 : ORDER BY deal_id LIMIT 100 OFFSET 100
    A-->>E: 100 rows. Ties re-ordered, so some page-1 rows appear again
    Note right of A: and rows that ranked 100-199<br/>last time now rank below 100,<br/>so they are never returned
    E->>A: 35 more pages
    A-->>E: 3,606 rows in total
    Note over E,A: 26 rows never returned. 26 returned twice.<br/>Count is still exactly 3,606.
    E->>E: reconcile on row count : PASSES
    E->>E: dbt grain uniqueness test : FAILS
```

**What to look at.** This one actually happened during the build. A count-based reconciliation passed. The only thing that caught it was a grain uniqueness test in dbt, which is the argument for keeping those tests on every staging model.

<a id="s2"></a>

## §2 The five source systems

Cardinalities and row counts are measured, not read off the schema. The annotations on the columns are the landmines: what is CHAR-padded, which dates are sentinels, which enums need a lookup, which key is not a key.

### Fig 2.1 — Sage X3 — ERP

*Every relationship resolves 100% after trimming. The risk in this estate is entirely at the system boundaries.*

```mermaid
erDiagram
    COMPANY ||--o{ FACILITY : "LEGCPY_0"
    FACILITY ||--o{ ITMFACILIT : "STOFCY_0"
    FACILITY ||--o{ SORDER : "SALFCY_0"
    FACILITY ||--o{ PORDER : "POHFCY_0"
    FACILITY ||--o{ GACCENTRY : "FCY_0"
    FACILITY ||--o{ STOCK : "STOFCY_0"
    FACILITY ||--o{ STOJOU : "STOFCY_0"
    FACILITY ||--o{ REPRESENT : "FCY_0"

    BPARTNER ||--o| BPCUSTOMER : "220 of 265"
    BPARTNER ||--o| BPSUPPLIER : "45 of 265"
    BPARTNER ||--o{ BPADDRESS : "BPANUM_0"
    BPARTNER ||--o{ GACCENTRYD : "BPR_0"

    REPRESENT ||--o{ BPCUSTOMER : "REP_0 and REP_1"
    REPRESENT ||--o{ SORDER : "REP_0 and REP_1"

    ITMMASTER ||--o{ ITMFACILIT : "ITMREF_0"
    ITMMASTER ||--o{ SORDERQ : "trim needed"
    ITMMASTER ||--o{ SORDERP : "trim needed"
    ITMMASTER ||--o{ SINVOICED : "ITMREF_0"
    ITMMASTER ||--o{ PORDERQ : "ITMREF_0"
    ITMMASTER ||--o{ STOCK : "ITMREF_0"
    ITMMASTER ||--o{ STOJOU : "trim needed"
    ITMMASTER ||--o{ ATEXTRA : "IDENT1_0"

    BPCUSTOMER ||--o{ SORDER : "BPCORD_0 trim needed"
    BPCUSTOMER ||--o{ SINVOICEV : "BPR_0"
    BPSUPPLIER ||--o{ PORDER : "BPSNUM_0"

    SORDER ||--o{ SORDERQ : "quantity side"
    SORDER ||--o{ SORDERP : "price side"
    SORDER ||--o{ STOJOU : "VCRNUM_0 where SDH"
    SORDERQ ||--o| SINVOICED : "SOHNUM_0 and SOPLIN_0"

    SINVOICEV ||--o{ SINVOICED : "NUM_0"
    SINVOICEV ||--o| GACCENTRY : "VCRNUM_0"

    PORDER ||--o{ PORDERQ : "POHNUM_0"
    GACCENTRY ||--o{ GACCENTRYD : "NUM_0"

    APLSTD ||--o{ ITMMASTER : "chapter 20 ITMSTA_0"
    APLSTD ||--o{ SORDER : "chapter 415 ORDSTA_0"
    APLSTD ||--o{ PORDER : "chapter 415 ORDSTA_0"
    APLSTD ||--o{ STOJOU : "chapter 700 TRSTYP_0"
    APLSTD ||--o{ ITMFACILIT : "chapter 861 REOMODE_0"

    COMPANY {
        varchar CPY_0 PK "2 rows: GLBUS, GLBCA"
        varchar CPYNAM_0
        varchar CRY_0
    }
    FACILITY {
        varchar FCY_0 PK "3 rows: US001 US002 CA001"
        varchar LEGCPY_0 FK
        varchar FCYNAM_0
        varchar CTY_0
    }
    BPARTNER {
        varchar BPRNUM_0 PK "265 rows"
        varchar BPRNAM_0
        bigint BPCFLG_0 "2 means customer"
        bigint BPSFLG_0 "2 means supplier"
        varchar CUR_0 "USD 229, CAD 36"
        bigint UPDTICK_0 "CDC hook"
    }
    BPCUSTOMER {
        varchar BPCNUM_0 PK "220 rows"
        varchar BPCNAM_0 "only link to HubSpot"
        varchar CUR_0
        varchar PTE_0 "payment terms"
        numeric BPCSNC_0 "credit limit"
        varchar REP_0 FK "array position 0"
        varchar REP_1 FK "array position 1, 41 rows"
    }
    BPSUPPLIER {
        varchar BPSNUM_0 PK "45 rows"
        varchar BPSNAM_0
        bigint LTI_0 "lead time days"
    }
    BPADDRESS {
        varchar BPANUM_0 PK "321 rows"
        varchar BPAADD_0 PK "multiple ship-tos"
        varchar CTY_0
    }
    REPRESENT {
        varchar REPNUM_0 PK "28 rows"
        varchar REPNAM_0 "LASTNAME FIRSTNAME"
        varchar FCY_0 FK
    }
    ITMMASTER {
        varchar ITMREF_0 PK "420 rows, NOT padded"
        varchar ITMDES1_0
        varchar TCLCOD_0 "category"
        bigint ITMSTA_0 "local menu ch 20"
        numeric BASPRI_0
        bigint UPDTICK_0 "CDC hook"
    }
    ITMFACILIT {
        varchar ITMREF_0 PK "886 rows"
        varchar STOFCY_0 PK
        bigint REOMODE_0 "local menu ch 861"
        numeric SAFSTO_0
    }
    SORDER {
        varchar SOHNUM_0 PK "4200 rows"
        varchar BPCORD_0 FK "CHAR-padded, all rows"
        varchar SALFCY_0 FK
        date ORDDAT_0
        date SHIDAT_0 "402 rows carry 1753-01-01"
        bigint ORDSTA_0 "local menu ch 415"
        varchar CUR_0 "USD 3512, CAD 688"
        varchar REP_0 FK
    }
    SORDERQ {
        varchar SOHNUM_0 PK "11575 rows"
        bigint SOPLIN_0 PK
        varchar ITMREF_0 FK "CHAR-padded, all rows"
        numeric QTY_0
        date DEMDLVDAT_0 "customer request date"
        numeric SHTQTY_0
    }
    SORDERP {
        varchar SOHNUM_0 PK "11575 rows"
        bigint SOPLIN_0 PK
        varchar ITMREF_0 FK "CHAR-padded, agrees with SORDERQ"
        varchar ITMDES1_0 "denormalised at order time"
        numeric NETPRI_0
        numeric AMTNOTLIN_0
    }
    SINVOICEV {
        varchar NUM_0 PK "3564 rows"
        varchar BPR_0 FK
        date INVDAT_0
        date PAYDAT_0 "492 rows carry 1753-01-01"
        varchar SIVTYP_0 "only value is SIN"
        numeric AMTNOTLIN_0
    }
    SINVOICED {
        varchar NUM_0 PK "9767 rows"
        bigint SIDLIN_0 PK
        varchar SOHNUM_0 FK "back-reference, 100 percent clean"
        bigint SOPLIN_0 FK
        numeric AMTNOTLIN_0 "sums to GL 41000 exactly"
    }
    PORDER {
        varchar POHNUM_0 PK "1400 rows"
        varchar BPSNUM_0 FK
        bigint ORDSTA_0 "local menu ch 415"
    }
    PORDERQ {
        varchar POHNUM_0 PK "2959 rows"
        bigint POPLIN_0 PK
        numeric RCPQTY_0 "receipt is a column, not a table"
        date RCPDAT_0 "576 rows carry 1753-01-01"
    }
    STOCK {
        varchar STOFCY_0 PK "1315 rows, current only"
        varchar ITMREF_0 PK
        varchar LOT_0 PK
        varchar LOC_0 PK
        numeric QTYSTU_0
    }
    STOJOU {
        bigint ROWID PK "16421 rows"
        varchar ITMREF_0 FK "CHAR-padded, all rows"
        bigint TRSTYP_0 "local menu ch 700, no return type"
        varchar VCRTYP_0 "SDH PTH ADJ only"
        varchar VCRNUM_0 "PTH rows do not resolve to PORDER"
        numeric QTYSTU_0
    }
    GACCENTRY {
        varchar NUM_0 PK "3564 rows"
        varchar JOU_0 "only value is SAL"
        varchar TYP_0 "only value is SIH"
        varchar VCRNUM_0 FK "the invoice"
        varchar CUR_0
    }
    GACCENTRYD {
        varchar NUM_0 PK "10692 rows"
        bigint LIN_0 PK
        varchar ACC_0 "only 11100, 22300, 41000"
        numeric AMTCUR_0 "document currency"
        numeric AMTLOC_0 "company currency, implies FX"
    }
    APLSTD {
        bigint CHAPTER_0 PK "16 rows"
        bigint CODE_0 PK
        varchar LANNUM_0 PK
        varchar TEXTE_0
    }
    ATEXTRA {
        varchar CODFIC_0 PK "136 rows"
        varchar ZONE_0 PK
        varchar LANNUM_0 PK "FRA translations"
        varchar IDENT1_0 PK
    }
```

**What to look at.** Two things to notice: SORDERQ and SORDERP split one logical order line across two physical tables, and STOJOU reconciles on the sales side but not the purchase side — all 10,421 shipment movements reach an order, none of the 4,217 receipts reach a purchase order.

### Fig 2.2 — HubSpot — CRM

*A connector landing: string properties, associations as a separate many-to-many, archived instead of deletes.*

```mermaid
erDiagram
    owner ||--o{ company : "hubspot_owner_id, 235 of 260"
    owner ||--o{ contact : "hubspot_owner_id, 765 of 940"
    owner ||--o{ deal : "hubspot_owner_id, 850 of 850"
    owner ||--o{ engagement : "owner_id"
    owner ||--o{ deal_stage_history : "changed_by_owner_id"

    company ||--o{ contact : "associatedcompanyid"
    company ||--o{ deal : "associated_company_id"
    company ||--o{ engagement : "associated_company_id"

    deal ||--o{ deal_stage_history : "deal_id"
    deal ||--o{ engagement : "associated_deal_id"
    pipeline_stage ||--o{ deal : "pipeline and dealstage"

    deal ||--o{ association : "850 deal to company"
    contact ||--o{ association : "940 contact to company"

    company {
        varchar id PK "260 rows, 12 archived"
        varchar name "the only link to X3"
        varchar domain "truncated to 18 chars, 198 distinct"
        varchar industry
        varchar numberofemployees "varchar, needs cast"
        varchar annualrevenue "varchar, needs cast"
        boolean archived "not a delete"
        date hs_lastmodifieddate "CDC hook"
    }
    contact {
        varchar id PK "940 rows, 23 archived"
        varchar email "40 near-duplicates, mangled"
        varchar associatedcompanyid FK
        varchar lifecyclestage
        boolean archived
    }
    deal {
        varchar id PK "850 rows, 11 archived"
        varchar amount "varchar, needs cast"
        varchar dealstage FK
        varchar erp_order_number "145 populated, 96 join as-is"
        boolean hs_is_closed_won "238 rows"
        varchar hs_deal_stage_probability "varchar"
        varchar associated_company_id FK
    }
    deal_stage_history {
        varchar deal_id PK "3606 rows"
        varchar stage PK
        date changed_at PK
    }
    engagement {
        varchar id PK "3000 rows"
        varchar type "call, email, meeting"
        varchar associated_deal_id FK
    }
    owner {
        varchar id PK "22 rows"
        varchar email "matches Paycom work_email exactly"
        varchar first_name
        varchar last_name
    }
    pipeline_stage {
        varchar pipeline_id PK "14 rows"
        varchar stage_id PK
        boolean is_closed
        boolean is_closed_won
    }
    association {
        varchar from_object_type PK "2599 rows"
        varchar from_id PK
        varchar to_object_type PK
        varchar to_id PK
    }
```

**What to look at.** company.name is the only candidate join to the ERP, and hubspot.owner.email is an exact match to Paycom's work_email — the best identity key in the estate, and not in the documented join map.

### Fig 2.3 — Paycom — payroll

*Flat report exports. Every date a string, every amount a string, and no change-tracking column anywhere.*

```mermaid
erDiagram
    employee ||--o{ check : "employee_code"
    check ||--o{ earning_detail : "check_id"
    check ||--o{ deduction_detail : "check_id"
    check ||--o{ tax_detail : "check_id"
    gl_mapping }o--o{ earning_detail : "code, 0 rows reach the GL"

    employee {
        varchar employee_code PK "150 rows for 138 people"
        varchar work_email "12 duplicated across 2 codes"
        varchar legal_first_name
        varchar legal_last_name
        varchar hire_date "MM/DD/YYYY string"
        varchar termination_date "MM/DD/YYYY string"
        varchar location_code "DAL-01, not US001"
        varchar annual_salary "string"
        varchar department_code "100 to 600"
    }
    check {
        varchar check_id PK "6752 rows, biweekly"
        varchar employee_code FK
        varchar check_date "MM/DD/YYYY string"
        varchar gross_pay "string"
        varchar net_pay "string"
        varchar location_code
    }
    earning_detail {
        varchar check_id PK "9526 rows"
        varchar earning_code PK "REG OT COMM PTO"
        varchar hours "string"
        varchar amount "string"
        varchar labor_allocation_code "DAL-01-200 style"
    }
    deduction_detail {
        varchar check_id PK "16481 rows"
        varchar deduction_code PK
        varchar ee_amount "string"
        varchar er_amount "string"
    }
    tax_detail {
        varchar check_id PK "33760 rows"
        varchar tax_code PK
        varchar ee_amount "string"
    }
    gl_mapping {
        varchar code_type PK "11 rows"
        varchar code PK
        varchar gl_account "50100-50140, 21500-21700"
    }
```

**What to look at.** employee_code is a primary key that does not identify a person: 12 emails appear twice with the same legal name and two different codes. gl_mapping is drawn as a solid line in the documented join map and is not one — none of its GL accounts exist in the ledger.

### Fig 2.4 — Netstock — demand planning

*Regenerated wholesale on each sync, with one last_sync_at across every row.*

```mermaid
erDiagram
    supplier ||--o{ item_location : "supplier_code, 100 percent"
    item_location ||--o{ forecast : "item and location"
    item_location ||--o{ forecast_accuracy : "item and location"
    item_location ||--o{ replenishment_recommendation : "item and location"

    item_location {
        varchar item_code PK "896 rows, 35 orphaned from X3"
        varchar location_code PK "uses X3 site codes, clean"
        varchar abc_class "A B C"
        varchar xyz_class
        bigint lead_time_days
        numeric reorder_point_qty
        varchar supplier_code FK
        date last_sync_at "2026-09-02 on every row"
    }
    forecast {
        varchar item_code PK "21504 rows"
        varchar location_code PK
        date period_start PK "monthly, 2025-09 to 2027-08"
        numeric forecast_qty
        varchar forecast_method
    }
    forecast_accuracy {
        varchar item_code PK "10752 rows"
        varchar location_code PK
        date period_start PK
        numeric abs_pct_error
    }
    replenishment_recommendation {
        varchar recommendation_id PK "896 rows"
        varchar erp_po_number FK "247 populated, all 247 resolve"
        varchar status "OPEN ACCEPTED REJECTED EXPIRED"
        numeric recommended_qty
    }
    supplier {
        varchar supplier_code PK "45 rows"
        varchar supplier_name
        bigint lead_time_days
    }
```

**What to look at.** replenishment_recommendation.erp_po_number is a clean cross-system link the documented join map does not mention: sparse at 247 of 896 rows, but 100% accurate where present. It is the only reliable path from planning back to procurement.

### Fig 2.5 — Pangea — freight visibility

*Product still unidentified, but the data is internally consistent with a freight platform.*

```mermaid
erDiagram
    carrier ||--o{ shipment : "carrier_scac, 100 percent"
    carrier ||--o{ shipment_leg : "carrier_scac"
    shipment ||--o{ shipment_leg : "shipment_id"
    shipment ||--o{ tracking_event : "shipment_id"
    shipment ||--o{ charge : "shipment_id"

    shipment {
        varchar shipment_id PK "3509 rows"
        varchar reference_number "X3 order on 2998, null on 247"
        varchar customer_name "matches X3 on all 220 values"
        varchar carrier_scac FK
        varchar origin_site_code "matches X3 FCY_0 on all rows"
        date ship_date
        date estimated_delivery_date "carrier promise"
        date delivered_date "null on 128"
        varchar status "DELIVERED 3381, EXCEPTION 109, IN_TRANSIT 19"
        numeric total_cost_usd "disagrees with charges on all rows"
    }
    tracking_event {
        varchar shipment_id PK "24504 rows"
        bigint event_seq PK
        varchar event_code "PU DP AR IT OD DL EX"
        date event_ts "316 rows out of order vs event_seq"
        varchar event_location
    }
    charge {
        varchar shipment_id PK "8277 rows"
        varchar charge_code PK "FREIGHT FUEL DETENTION LIFTGATE RESIDENTIAL"
        numeric amount_usd
        varchar currency "USD only"
    }
    shipment_leg {
        varchar shipment_id PK "5415 rows"
        bigint leg_seq PK
        varchar carrier_scac FK
        date depart_ts
        date arrive_ts
    }
    carrier {
        varchar scac PK "7 rows"
        varchar carrier_name
        varchar mode "PARCEL LTL TL"
    }
```

**What to look at.** Two structural facts drive everything built on top: the header cost and the charge lines never agree, and event timestamps are not monotonic in event_seq — so milestones are extracted by event code, never by earliest timestamp.

<a id="s3"></a>

## §3 Where the systems meet

The part that matters for the design. Solid arrows are keys that resolve. Dashed arrows are the seams, and each one carries its measured cost.

### Fig 3.1 — The cross-system join map

*Three of the seven cross-system links are not in the documented join map, and two of those are the best keys available.*

```mermaid
flowchart TB
    subgraph X3["sage_x3 (ERP)"]
        direction TB
        x3_item["ITMMASTER<br/>420 items"]
        x3_cust["BPCUSTOMER<br/>220 customers"]
        x3_supp["BPSUPPLIER<br/>45 suppliers"]
        x3_site["FACILITY<br/>3 sites"]
        x3_order["SORDER<br/>4,200 orders"]
        x3_po["PORDER<br/>1,400 POs"]
        x3_rep["REPRESENT<br/>28 reps"]
        x3_gl["GACCENTRYD<br/>3 accounts"]
    end

    subgraph HS["hubspot (CRM)"]
        direction TB
        hs_co["company<br/>260"]
        hs_deal["deal<br/>850"]
        hs_owner["owner<br/>22"]
    end

    subgraph PG["pangea (freight)"]
        direction TB
        pg_ship["shipment<br/>3,509"]
    end

    subgraph NS["netstock (planning)"]
        direction TB
        ns_il["item_location<br/>896"]
        ns_rec["replenishment<br/>896"]
        ns_supp["supplier<br/>45"]
    end

    subgraph PC["paycom (payroll)"]
        direction TB
        pc_emp["employee<br/>150 rows / 138 people"]
        pc_gl["gl_mapping<br/>11"]
    end

    ns_il ==>|"item_code<br/>861 of 896 · 35 orphans"| x3_item
    ns_il ==>|"location_code<br/>100%"| x3_site
    ns_supp ==>|"supplier_code<br/>100%"| x3_supp
    ns_rec ==>|"erp_po_number<br/>247 of 247 populated<br/>NOT in the join map"| x3_po
    pg_ship ==>|"origin_site_code<br/>100%"| x3_site
    pg_ship ==>|"customer_name<br/>220 of 220 distinct<br/>NOT in the join map"| x3_cust
    hs_owner ==>|"email = work_email<br/>22 of 22<br/>NOT in the join map"| pc_emp

    pg_ship -.->|"reference_number<br/>2,998 of 3,509 (85.4%)<br/>247 null · 264 customer PO"| x3_order
    hs_deal -.->|"erp_order_number<br/>96 raw, 145 repaired<br/>of 238 closed-won"| x3_order
    hs_co -.->|"name only, no key<br/>171 exact, 229 with probes<br/>31 unmatched (11.9%)"| x3_cust
    x3_rep -.->|"name only<br/>28 reps, 30 rows before dedup"| pc_emp
    pc_gl -.->|"gl_account<br/>0 of 11 accounts exist<br/>README calls this solid"| x3_gl

    classDef clean stroke:#2f7d32,stroke-width:2px
    classDef broken stroke:#b3261e,stroke-width:2px,stroke-dasharray:4 3
    class x3_order,x3_cust,x3_gl broken
```

**What to look at.** The dashed lines are where the sprint goes. Tiered matching takes HubSpot-to-ERP customer coverage from 65.8% to 88.1%; repairing case, prefix and multi-value references takes the CRM-to-ERP handoff from 96 deals to 145.

<a id="s4"></a>

## §4 The model the dashboards read

One conformed core, process-agnostic. Five dimensions, four atomic facts, and every fact-to-dimension relationship asserted by a test rather than assumed by the BI tool.

### Fig 4.1 — The dimensional model

*Five conformed dimensions and four atomic facts. Nine presentation views sit on top; none of them contain business logic.*

```mermaid
erDiagram
    dim_date ||--o{ fct_shipment : "ship_date_key"
    dim_date ||--o{ fct_shipment_event : "event_date_key"
    dim_date ||--o{ fct_sales_order_line : "order_date_key"
    dim_date ||--o{ fct_invoice_line : "invoice_date_key"

    dim_customer ||--o{ fct_shipment : "customer_key"
    dim_customer ||--o{ fct_shipment_event : "customer_key"
    dim_customer ||--o{ fct_sales_order_line : "customer_key"
    dim_customer ||--o{ fct_invoice_line : "customer_key"

    dim_site ||--o{ fct_shipment : "site_code"
    dim_site ||--o{ fct_shipment_event : "site_code"
    dim_site ||--o{ fct_sales_order_line : "site_code"
    dim_site ||--o{ fct_invoice_line : "site_code"

    dim_item ||--o{ fct_sales_order_line : "item_code"
    dim_item ||--o{ fct_invoice_line : "item_code"

    dim_carrier ||--o{ fct_shipment : "carrier_scac"
    dim_carrier ||--o{ fct_shipment_event : "carrier_scac"

    fct_shipment ||--o{ fct_shipment_event : "shipment_id"

    dim_date {
        integer date_key PK "1461 rows, 2024-2027"
        date date_day
        integer calendar_year
        integer calendar_quarter
        varchar fiscal_quarter_label "fiscal equals calendar, ASSUMED"
        boolean fiscal_equals_calendar "the assumption, visible"
        boolean is_past_as_of_build "named for what it is, not is_past"
        date built_on_date "so a stale value is visible"
    }
    dim_customer {
        varchar customer_key PK "252 rows incl UNKNOWN"
        varchar customer_code "X3, null for CRM-only"
        varchar hubspot_company_id "CRM, null for ERP-only"
        varchar customer_name "X3 survives"
        varchar payment_term_code "X3 survives"
        numeric credit_limit_amount "X3 survives"
        varchar primary_rep_name "X3 survives"
        varchar industry "HubSpot survives"
        double annual_revenue "HubSpot survives"
        varchar source_scope "both 197, erp 23, crm 31, unknown 1"
        decimal match_confidence "0.60 to 0.95"
        boolean match_is_ambiguous "15 rows"
        integer crm_company_count "makes the CRM denominator recoverable"
    }
    dim_site {
        varchar site_code PK "4 rows incl UNKNOWN"
        varchar site_name
        varchar paycom_location_code "via seed crosswalk"
        varchar netstock_location_code
        varchar company_name
    }
    dim_item {
        varchar item_code PK "421 rows incl UNKNOWN"
        varchar item_description "current, not order-time"
        varchar item_status "decoded from local menu"
        varchar best_abc_class "strongest class at any location"
        boolean is_planned_in_netstock "418 of 420"
    }
    dim_carrier {
        varchar carrier_scac PK "8 rows incl UNKNOWN"
        varchar carrier_name
        varchar transport_mode
        bigint shipment_count
    }
    fct_shipment {
        varchar shipment_id PK "3509 rows"
        integer ship_date_key FK
        varchar customer_key FK "resolved on 100 percent"
        varchar site_code FK
        varchar carrier_scac FK
        varchar sales_order_number "resolved on 85.4 percent"
        numeric shipment_cost_usd "resolves to var shipment_cost_basis"
        numeric header_cost_usd "the other basis"
        numeric cost_variance_usd "never zero"
        boolean is_on_time_vs_carrier_promise "75.6 percent"
        boolean is_on_time_vs_customer_request "84.1 percent"
        boolean has_order_reference
        boolean has_out_of_sequence_events "298 shipments"
    }
    fct_shipment_event {
        varchar shipment_id PK "24504 rows"
        bigint event_sequence PK
        varchar event_code
        date event_at "not event_date - a real feed sends a timestamp"
        integer days_since_previous_event
        boolean is_out_of_sequence "316 events"
    }
    fct_sales_order_line {
        varchar sales_order_number PK "11575 rows"
        bigint sales_order_line_number PK
        varchar customer_key FK
        varchar item_code FK
        numeric line_net_amount_doc "document currency"
        numeric line_net_amount_usd "reporting currency"
        decimal fx_rate "from int_fx_rate"
        boolean fx_rate_is_fallback "0 rows today"
    }
    fct_invoice_line {
        varchar invoice_number PK "9767 rows"
        bigint invoice_line_number PK
        varchar customer_key FK
        numeric line_net_amount_usd "sums to GL 41000 exactly"
        integer days_to_pay_settled_only "the only one - null, never zero, when unpaid"
        boolean is_unsettled "1335 lines, 13.7 percent"
    }
```

**What to look at.** dim_customer carries its own entity-resolution result: 197 matched across both systems, 23 ERP-only, 31 CRM companies with no ERP counterpart. Those 31 stay in the dimension, because dropping them would make the unmatched rate look like zero.

<a id="s5"></a>

## §5 How one becomes the other

Extracted from the dbt manifest after a full build — this is what actually runs. 80 models across five layers, fed by 46 extraction resources.

### Fig 5.1 — The whole pipeline

*Source systems to exports, by layer, with what each layer is allowed to do.*

```mermaid
flowchart TB
    subgraph SYS["source systems"]
        y1["Sage X3<br/><i>SQL database read</i>"]
        y2["HubSpot<br/><i>REST + cursor</i>"]
        y3["Paycom<br/><i>SFTP report drop</i>"]
        y4["Netstock<br/><i>snapshot API</i>"]
        y5["Pangea<br/><i>REST + children</i>"]
    end

    subgraph ING["ingestion · dlt · 46 resources"]
        ext["extract<br/><br/>10 full refresh · 3 modified-date<br/>12 header-window · 5 API cursor<br/>5 snapshot · 6 file drop<br/><br/>schema contract enforced"]
        land[("landing/<br/>Parquet · append-only<br/>partitioned by load_date<br/><i>replayable · auditable</i>")]
    end

    subgraph SRC["raw.duckdb · 46 tables · 233,150 rows"]
        s1["sage_x3 · 22"]
        s2["hubspot · 8"]
        s3["paycom · 6"]
        s4["netstock · 5"]
        s5["pangea · 5"]
    end

    subgraph STG["staging · 46 models · generated"]
        stg["stg_&lt;source&gt;__&lt;table&gt;<br/><br/>trim · sentinel to null · cast<br/>parse dates · decode local menus<br/>flag archived, never filter<br/><br/>NO business logic"]
    end

    subgraph INT["intermediate · 8 models · hand-written"]
        i1["int_customer_xref"]
        i2["int_employee_xref"]
        i3["int_deal_erp_order_number"]
        i4["int_fx_rate"]
        i5["int_sales_order_line"]
        i6["int_shipment_order"]
        i7["int_shipment_charge"]
        i8["int_shipment_milestone"]
    end

    subgraph CORE["marts/core · 9 models · hand-written · THE data model"]
        d["dim_date · dim_customer · dim_site<br/>dim_item · dim_carrier"]
        f["fct_shipment · fct_shipment_event<br/>fct_sales_order_line · fct_invoice_line"]
    end

    subgraph SEM["semantic · 10 metric definitions · YAML"]
        reg["semantic/metrics/*.yml<br/>semantic/models.yml<br/>semantic/dimensions.yml<br/><br/>no process field"]
    end

    subgraph MTR["marts/metrics · 7 models · generated"]
        m["mtr_&lt;metric&gt;<br/>numerator + denominator by dimension"]
    end

    subgraph PROC["marts/process · 9 views · generated"]
        p["mart_o2c · mart_s2p · mart_i2d<br/>+ 6 empty and typed"]
    end

    subgraph OUT["exports"]
        o["Parquet · TMDL · DAX<br/>Cube schema · agent JSON"]
    end

    seed[("seeds<br/>process_metric_map<br/>site_code_crosswalk<br/>process · metric_registry")]

    SYS --> ext --> land -->|"projection: SQL only,<br/>no source access"| SRC
    SRC --> STG --> INT --> CORE
    CORE --> reg
    reg -->|"scripts/compile_metrics.py"| MTR
    reg -->|"scripts/compile_metrics.py"| OUT
    MTR --> PROC
    seed -->|"scripts/generate_process_views.py"| PROC
    seed --> CORE
    CORE --> OUT
    reg -->|"compile"| seed
```

**What to look at.** The two arrows leaving the semantic layer are the point of the design: one YAML definition generates both the warehouse SQL and the Power BI measures, so a dashboard and the database cannot disagree about what a metric means.

### Fig 5.2 — Shipment path

*The deepest chain in the project, carrying both computable metrics.*

```mermaid
flowchart LR
    src_ship[("pangea.shipment")] --> stg_ship["stg_pangea__shipment"]
    src_evt[("pangea.tracking_event")] --> stg_evt["stg_pangea__tracking_event"]
    src_chg[("pangea.charge")] --> stg_chg["stg_pangea__charge"]
    src_car[("pangea.carrier")] --> stg_car["stg_pangea__carrier"]
    src_ord[("sage_x3.SORDER")] --> stg_ord["stg_sage_x3__sorder"]
    src_ordq[("sage_x3.SORDERQ")] --> stg_ordq["stg_sage_x3__sorderq"]
    src_cust[("sage_x3.BPCUSTOMER")] --> stg_cust["stg_sage_x3__bpcustomer"]

    stg_ship --> int_chg["int_shipment_charge<br/><i>both cost bases + variance</i>"]
    stg_chg --> int_chg
    stg_evt --> int_ms["int_shipment_milestone<br/><i>by event_code, not min ts</i>"]
    stg_ship --> int_ord["int_shipment_order<br/><i>order 85.4% · customer 100%</i>"]
    stg_ord --> int_ord
    stg_ordq --> int_ord
    stg_cust --> int_ord

    stg_ship --> fct["fct_shipment<br/><i>3,509 rows</i>"]
    int_chg --> fct
    int_ms --> fct
    int_ord --> fct

    stg_evt --> fevt["fct_shipment_event<br/><i>24,504 rows</i>"]
    fct --> fevt
    stg_car --> dcar["dim_carrier"]
    stg_ship --> dcar

    fct --> mtr1["mtr_on_time_delivery_rate"]
    fct --> mtr2["mtr_cost_per_shipment"]
    fct --> mtr3["mtr_cost_per_order"]
    fct --> mtr4["mtr_order_reference_coverage_rate"]

    mtr1 --> i2d["mart_i2d"]
    mtr2 --> i2d
    mtr3 --> o2c["mart_o2c"]
```

**What to look at.** fct_shipment feeds four metrics across two different dashboards. That is the conformed core doing its job — one shipment fact, not an I2D shipment fact and an O2C shipment fact.

### Fig 5.3 — Order-to-cash path

*X3's split line tables rejoined, and both money facts converted through one rate model.*

```mermaid
flowchart LR
    src_sq[("SORDERQ<br/>quantity")] --> stg_sq["stg_sage_x3__sorderq"]
    src_sp[("SORDERP<br/>price")] --> stg_sp["stg_sage_x3__sorderp"]
    src_so[("SORDER")] --> stg_so["stg_sage_x3__sorder"]
    src_iv[("SINVOICEV")] --> stg_iv["stg_sage_x3__sinvoicev"]
    src_id[("SINVOICED")] --> stg_id["stg_sage_x3__sinvoiced"]
    src_gl[("GACCENTRY<br/>GACCENTRYD")] --> stg_gl["stg_sage_x3__gaccentry(d)"]
    src_bc[("BPCUSTOMER")] --> stg_bc["stg_sage_x3__bpcustomer"]
    src_ap[("APLSTD")] --> stg_ap["stg_sage_x3__aplstd"]

    stg_ap -.->|"decode ORDSTA_0"| stg_so
    stg_sq --> int_sol["int_sales_order_line<br/><i>rejoins the split tables</i>"]
    stg_sp --> int_sol
    stg_gl --> int_fx["int_fx_rate<br/><i>rate recovered from the GL</i>"]

    int_sol --> fsol["fct_sales_order_line<br/><i>11,575 rows</i>"]
    stg_so --> fsol
    int_fx --> fsol

    stg_id --> fil["fct_invoice_line<br/><i>9,767 rows · ties to GL 41000</i>"]
    stg_iv --> fil
    stg_bc --> fil
    int_fx --> fil

    fil --> mtr_dso["mtr_dso_days_to_pay_proxy"]
    fil --> mtr_uns["mtr_unsettled_invoice_rate<br/><i>mandatory companion</i>"]
    mtr_dso --> o2c["mart_o2c"]
```

**What to look at.** int_fx_rate feeding both facts is what stops USD and CAD being added together by accident. Every monetary column exists twice, suffixed _doc and _usd.

### Fig 5.4 — Entity resolution

*Two crosswalks, one reference repair — and two models with nothing downstream of them.*

```mermaid
flowchart LR
    hs_co[("hubspot.company<br/>260")] --> stg_hco["stg_hubspot__company"]
    x3_bc[("sage_x3.BPCUSTOMER<br/>220")] --> stg_bc["stg_sage_x3__bpcustomer"]
    x3_bp[("sage_x3.BPARTNER")] --> stg_bp["stg_sage_x3__bpartner"]
    x3_rp[("sage_x3.REPRESENT<br/>28")] --> stg_rp["stg_sage_x3__represent"]
    pc_emp[("paycom.employee<br/>150")] --> stg_emp["stg_paycom__employee"]
    hs_own[("hubspot.owner<br/>22")] --> stg_own["stg_hubspot__owner"]
    hs_deal[("hubspot.deal<br/>850")] --> stg_deal["stg_hubspot__deal"]
    x3_so[("sage_x3.SORDER")] --> stg_so["stg_sage_x3__sorder"]

    stg_hco --> xref_c["int_customer_xref<br/><i>4 probes with confidence</i><br/><i>310 candidate pairs</i>"]
    stg_bc --> xref_c

    stg_emp --> xref_e["int_employee_xref<br/><i>dedup Paycom FIRST</i><br/><i>then match</i>"]
    stg_rp --> xref_e
    stg_own --> xref_e

    stg_deal --> repair["int_deal_erp_order_number<br/><i>case · prefix · multi-value</i><br/><i>96 to 145 deals</i>"]
    stg_so --> repair

    xref_c --> dcust["dim_customer<br/><i>251 rows</i><br/><i>197 both · 23 erp · 31 crm</i>"]
    stg_hco --> dcust
    stg_bc --> dcust
    stg_bp --> dcust
    stg_rp --> dcust

    dcust --> mtr_um["mtr_customer_unmatched_rate<br/><i>11.9% · on no dashboard</i>"]

    xref_e -. "no consumer yet" .-> none1["fct_payroll_earning<br/>fct_deal_stage_change<br/><i>not built</i>"]
    repair -. "no consumer yet" .-> none1

    style none1 stroke-dasharray:4 3
```

**What to look at.** int_employee_xref and int_deal_erp_order_number are built, tested and unconsumed. Their findings are governance results in their own right, and the resolution is ready for the first metric that needs it. The DAG shows the dead ends rather than hiding them.

### Fig 5.5 — Metric and dashboard generation

*The part with no dbt lineage, because the edges are scripts rather than model references.*

```mermaid
flowchart TB
    yml["semantic/metrics/*.yml<br/><b>10 definitions</b><br/>5 active · 2 provisional · 3 blocked"]
    mdl["semantic/models.yml<br/><i>fact to dimension bindings</i>"]
    dim["semantic/dimensions.yml<br/><i>the conformed dimensions</i>"]
    map["seeds/process_metric_map.csv<br/><b>7 rows</b><br/><i>the many-to-many</i>"]

    comp{{"scripts/compile_metrics.py<br/><i>validates, then compiles</i>"}}
    gen{{"scripts/generate_process_views.py"}}
    pbi{{"scripts/export_powerbi.py"}}

    yml --> comp
    mdl --> comp
    dim --> comp

    comp --> t1["models/marts/metrics/*.sql<br/><i>7 dbt models</i>"]
    comp --> t2["models/semantic/_semantic_models.yml<br/><i>MetricFlow · 1 metric skipped</i>"]
    comp --> t3["seeds/metric_registry.csv<br/><i>lets dbt test map vs registry</i>"]
    comp --> t4["exports/powerbi/measures.dax"]
    comp --> t5["exports/powerbi/tmdl/*.tmdl"]
    comp --> t6["exports/cube/model/cubes/*.yml"]
    comp --> t7["exports/semantic/metric_registry.json<br/><i>the agent contract</i>"]
    comp --> t8["docs/metric_catalog.md"]

    map --> gen
    yml --> gen
    gen --> views["models/marts/process/*.sql<br/><i>9 views · 3 populated · 6 empty</i>"]
    t1 --> views

    t5 --> pbi
    pbi --> model["exports/powerbi/model/definition/<br/><i>12 tables · 16 relationships</i><br/><i>7 measures · 0 hand-written</i>"]

    t3 -.->|"relationships test"| map
    t7 --> agent["scripts/ask_metric.py<br/><i>answers from the registry alone</i>"]
```

**What to look at.** The registry is compiled into a seed so dbt can enforce referential integrity between the dashboard map and the metric definitions. A typo fails the build instead of producing an empty tile.

---

Rebuild this page with `python scripts/build_atlas.py docs/atlas.md`.
