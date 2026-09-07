# Entity relationships and pipeline

Three views of the same system:

1. **[Source ERDs](#1-source-erds)** — what the five source systems look like, and
   which of their relationships actually hold.
2. **[Cross-system ERD](#2-cross-system-erd)** — where the systems touch, which
   of those seams are reliable, and the measured cost of the ones that are not.
3. **[The dimensional model](#3-the-dimensional-model)** — the star schema the
   dashboards are built on.
4. **[Pipeline DAGs](#4-pipeline-dags)** — how one becomes the other.

Every cardinality and every match rate on this page was measured against
`mock_sources.duckdb` (SEED 20260905) or read out of `target/manifest.json`.
Nothing here is drawn from the schema alone. Reproduce with
`python scripts/profile_sources.py`.

Diagrams render on GitHub and in any Mermaid-aware viewer. For the interactive
version of the DAGs, `dbt docs generate && dbt docs serve`.

---

## 1. Source ERDs

### 1.1 Sage X3 (ERP) — high fidelity

The ERP is where the transactional volume lives, and its internal referential
integrity is perfect: every relationship below resolves 100% **after trimming**.
Two things to notice in the diagram — `SORDERQ`/`SORDERP` split one logical
order line across two physical tables, and `APLSTD` is a generic enum table that
every status column resolves through.

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

**What the diagram is telling you**

- **Every X3 join resolves 100% after `trim()`.** The `trim needed` labels are
  not warnings about data quality — they are warnings about *your SQL*. Without
  the trim, `SORDERQ → ITMMASTER` returns **zero rows**, not fewer rows.
- **`SORDERQ ||--o| SINVOICED` is one-to-at-most-one.** All 9,767 invoice lines
  resolve to an order line, no order line is invoiced twice, and 9,767 of the
  11,575 order lines have been invoiced. Order-to-cash is fully traceable
  inside X3.
- **`STOJOU` has three document types and only one of them reconciles.** The
  10,421 `SDH` (shipment) rows all resolve to a `SORDER`. The 4,217 `PTH`
  (receipt) rows carry `PTH######` document numbers that match **nothing** in
  `PORDER` — so there is no path from a goods receipt back to its purchase
  order except the `RCPQTY_0`/`RCPDAT_0` columns on the PO line itself. That
  matters for Match Rate.
- **The GL is one journal wide.** `JOU_0` is `SAL` on all 3,564 rows, `TYP_0`
  is `SIH`, and `GACCENTRYD.ACC_0` holds exactly three accounts. There is no AP
  subledger and no cost accounting. This single fact blocks Match Rate and caps
  Cost Per Order at a fulfillment-only pool.

### 1.2 HubSpot (CRM) — connector landing

Shaped like a Fivetran/Airbyte landing: properties as strings, associations as
a separate many-to-many, `archived` instead of deletes. Note that
`association` duplicates what the denormalised `*_id` columns on `deal` and
`contact` already carry — both are present, as they would be in a real landing.

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

The 25 companies and 175 contacts with no owner are not an integrity failure —
`hubspot_owner_id` is genuinely optional in HubSpot. The 12 archived companies
are flagged in staging and left for the mart to decide about.

### 1.3 Paycom (payroll) — flat report exports

Paycom has no queryable backend, so this is modelled as report exports and that
is the real constraint. Every date is a `MM/DD/YYYY` string, every amount is a
string, and there is **no change-tracking column anywhere** — so ingestion is
full refresh, unlike X3 and HubSpot.

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

Two findings sit in this diagram:

- **`employee_code` is a primary key that does not identify a person.** 12
  emails appear twice with the same legal name and two different codes. The
  roster describes 138 people. This breaks both candidate cross-system keys and
  is why `int_employee_xref` deduplicates before it matches.
- **`gl_mapping` is drawn as a solid line in the README's join map and it is
  not one.** None of its 11 GL accounts exist in `GACCENTRYD`, which holds only
  11100, 22300 and 41000. Payroll is not posted to the general ledger in this
  extract.

### 1.4 Netstock (demand planning) — inferred

Regenerated wholesale on each sync with a single `last_sync_at` of 2026-09-02,
so the natural landing pattern is a snapshot fact rather than an SCD.

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

`replenishment_recommendation.erp_po_number` is a **clean cross-system link
that the README's join map does not mention** — sparse (247 of 896) but 100%
accurate where present, and spread across all four statuses rather than only
`ACCEPTED`. It is the only reliable path from planning back to procurement.

### 1.5 Pangea (freight visibility) — inferred, product unconfirmed

The product identity is a guess (open question 9). The data is internally
consistent with a freight/parcel visibility platform: SCAC-keyed carriers,
PARCEL/LTL/TL modes, tracking events, accessorial charges.

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

Two structural facts drive the model built on top of this:

- **`total_cost_usd` and `sum(charge.amount_usd)` never agree.** Not on one of
  3,509 shipments; only 30 agree within a dollar; the header is 9.9% higher in
  aggregate. `int_shipment_charge` computes both and publishes the variance.
- **`event_ts` is not monotonic in `event_seq`.** 316 events (1.29%) across 298
  shipments arrive out of order, so milestones are extracted by `event_code`,
  never by `min`/`max` of the timestamp.

---

## 2. Cross-system ERD

This is the part that matters for the design. **Solid lines resolve cleanly.
Dashed lines are the seams** — and every one of them has a measured cost.

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

Read with the arrows: `==>` is a reliable key, `-.->` is a seam that needs a
resolution strategy.

| Seam | Raw | After the work in `intermediate/` | Where |
|---|---|---|---|
| HubSpot company → X3 customer | 171 of 260 (65.8%) | **229 (88.1%)**, 15 ambiguous, 31 unmatched | `int_customer_xref` |
| HubSpot deal → X3 order | 96 of 145 | **145 of 145** (every deal carrying a reference) | `int_deal_erp_order_number` |
| Pangea shipment → X3 order | 2,998 of 3,509 (85.4%) | 85.4% for the order; **100% for the customer** via `customer_name` | `int_shipment_order` |
| X3 rep → Paycom employee | 30 rows for 28 reps | **28 unambiguous**, after deduplicating Paycom first | `int_employee_xref` |
| Paycom GL → X3 GL | 0 of 11 | Still 0. Not fixable here — it is a finding | warn test, threshold 11 |

Three of the seven links above are **not in the README's join map** and two of
them are the best keys available in the estate. The `hubspot.owner.email =
paycom.employee.work_email` link in particular is exact, where the documented
name-based path is not.

---

## 3. The dimensional model

Star schema. Five conformed dimensions, four atomic facts, all in
`marts/core/`. Process-agnostic by design — nothing in this layer knows what a
dashboard is.

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

**Grain, stated once**

| Model | One row is | Rows |
|---|---|---|
| `dim_date` | one calendar day | 1,461 |
| `dim_customer` | one conformed customer | 252 |
| `dim_site` | one site | 4 |
| `dim_item` | one item | 421 |
| `dim_carrier` | one carrier SCAC | 8 |
| `fct_shipment` | one shipment | 3,509 |
| `fct_shipment_event` | one tracking event on one shipment | 24,504 |
| `fct_sales_order_line` | one sales order line | 11,575 |
| `fct_invoice_line` | one sales invoice line | 9,767 |

Every one of the 16 fact-to-dimension relationships above is asserted by a dbt
`relationships` test, so the Power BI model is not relying on the tool to
discover a join that does not hold.

**Every dimension except `dim_date` carries an UNKNOWN member**, and every fact
coalesces its foreign keys to it — which is why the row counts are one above
the natural entity count. Without it an unresolved key lands as null:
`relationships` ignores nulls so it still passes, `not_null` on the fact starts
failing the build, and Power BI collects the rows on a blank member that reads
to a user as real. `dim_date` is the exception on purpose — an integer date key
has no sentinel that is not also a plausible date, and a fact with no date has
no place on a time series rather than an unknown one.

**Facts named but not built.** Grain decided once so it is not rediscovered
later: `fct_inventory_movement` (`STOJOU.ROWID`), `fct_inventory_balance` (item
× site × lot snapshot), `fct_purchase_order_line` (`POHNUM_0` + `POPLIN_0`),
`fct_gl_entry_line` (`NUM_0` + `LIN_0`), `fct_forecast` (item × location ×
period snapshot), `fct_deal_stage_change` (`deal_id` + transition),
`fct_payroll_earning` (`check_id` + `earning_code`). No active metric needs
them.

---

## 4. Pipeline DAGs

Extracted from `target/manifest.json` — this is what actually builds, not a
sketch. 80 models across five layers, fed by 46 dlt extraction resources.
See [ingestion.md](ingestion.md) for the extraction spec and its pitfalls.

### 4.1 The whole pipeline, by layer

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

The two arrows out of `semantic/` are the point of the whole design: the same
YAML produces the warehouse SQL *and* the Power BI measures, so they cannot
drift.

### 4.2 Shipment path — the I2D metrics

The deepest chain in the project, and the one carrying both computable metrics.

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

Note `fct_shipment` feeds four metrics across **two different dashboards**.
That is the conformed core doing its job — one shipment fact, not an I2D
shipment fact and an O2C shipment fact.

### 4.3 Order-to-cash path — the O2C metrics

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

`int_fx_rate` feeding both money facts is what stops USD and CAD amounts being
added together by accident — every monetary column exists as `_doc` and `_usd`.

### 4.4 Entity resolution path

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

**Two intermediate models have no downstream consumer.** `int_employee_xref`
and `int_deal_erp_order_number` are built, tested and documented but nothing in
`marts/core/` reads them, because no active metric needs an employee or a CRM
deal. They exist because the plan requires entity resolution to be first-class
and inspectable, and because their findings — 138 people behind 150 rows, 96 to
145 recoverable deals — are governance results the client needs whether or not
a dashboard consumes them. When `fct_payroll_earning` or
`fct_deal_stage_change` gets built, the resolution is already done and tested.

That is a deliberate choice, not an oversight, and it is the kind of thing a
DAG makes visible.

### 4.5 Metric and process generation

The part with no dbt lineage, because the edges are scripts rather than `ref()`.

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

Two edges are worth tracing:

- **`metric_registry.csv` back to `process_metric_map.csv`.** The registry is
  compiled into a seed so dbt can enforce referential integrity between the map
  and the definitions with an ordinary `relationships` test. A typo in the map
  fails the build instead of producing an empty dashboard tile.
- **`mart_s2p` has no incoming edge at all.** Its only metric, Match Rate, is
  blocked, so the view emits a single typed row carrying the blocked reason and
  references no model. Six other process views are the same. The DAG showing
  nothing upstream of them is correct and is what the empty case should look
  like.

### 4.6 What the DAGs do not show

- **210 tests.** They attach to models rather than sitting between them. 203
  pass, 4 warn with documented thresholds, 0 error.
- **Materialisation.** Staging, intermediate ratios and process views are
  views; `marts/core` and the three heavier intermediate models are tables.
  Everything is a full refresh — correct at 233,000 rows.
- **The ingestion asymmetry that will drive the real design.** X3 carries
  `UPDTICK_0` and HubSpot carries `hs_lastmodifieddate`, so both support
  incremental extraction. Paycom carries neither and is full-refresh-only. That
  belongs in the ingestion architecture, not in this pipeline.

---

## Regenerating these diagrams

The measured figures come from:

```bash
python scripts/profile_sources.py     # every source-side number
dbt docs generate                     # interactive DAG, full lineage
dbt docs serve
```

The lineage in section 4 was extracted from `target/manifest.json` after a full
`dbt build`. If you add a model, regenerate the manifest and check this page
still matches — a stale architecture diagram is worse than none, because people
trust it.
