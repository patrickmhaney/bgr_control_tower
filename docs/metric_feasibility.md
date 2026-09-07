# Phase 0 — Metric feasibility audit

Every number below was measured against `mock_sources.duckdb` (SEED 20260905),
not inferred. The queries are reproducible from `scripts/profile_sources.py`.

**Headline: three of the seven defined metrics cannot be computed from any
current source, and two more need a business decision before they mean
anything. Only two are computable as specified.** That is the most important
finding of the phase and it is a sourcing problem, not an engineering one.

| Metric | Process | Verdict | Registry status |
|---|---|---|---|
| Cost Per Shipment | I2D | Computable | `active` |
| On-Time Delivery | I2D | Computable, but "on time against what?" is unanswered | `active` (assumption flagged) |
| Cost Per Order | O2C | Needs an allocation rule | `provisional` |
| DSO | O2C | Proxy only — no cash application data exists | `provisional` |
| Return Rate | O2C | **Blocked** — no returns object in any source | `blocked` |
| Match Rate | S2P | **Blocked** — no supplier invoice table | `blocked` |
| Inventory Accuracy | I2D | **Blocked** — no cycle count data | `blocked` |

---

## Computable

### Cost Per Shipment — computable, one decision required

`pangea.charge` has 8,277 rows across 3,509 shipments; every shipment has at
least a FREIGHT charge, and all charges are USD.

| | |
|---|---|
| Shipments | 3,509 |
| Shipments with no charge lines | 0 |
| Sum of `shipment.total_cost_usd` | 6,030,476 |
| Sum of `charge.amount_usd` | 5,488,709 |
| Shipments where the two agree to the cent | **0 of 3,509** (30 within a dollar) |
| Mean (charges − header) | −154.39 |

Charge mix: FREIGHT (3,509 rows), FUEL (3,174), DETENTION (551), LIFTGATE
(524), RESIDENTIAL (519).

The header is 9.9% higher than the charge lines in total, and the disagreement
is not a rounding artefact — it is systematic. README landmine 13 attributes it
to accessorials posting late, but the direction here is the opposite (header
above lines), which suggests the header is an estimate/rated cost rather than a
late-posting artefact.

**Decision taken for the POC:** the metric uses the sum of charge lines
(`var: shipment_cost_basis = charge_lines`). Rationale: line-level cost is
auditable, reconcilable to carrier invoices, and decomposable by charge code —
a header number that no one can explain is not a governable metric. The header
is still carried on `fct_shipment` as `header_cost_usd` alongside
`cost_variance_usd`, so the variance is measurable rather than hidden, and
flipping the basis is a `dbt_project.yml` var change.

### On-Time Delivery — computable, but the answer depends on the promise

Both candidate promise dates exist, and they give materially different answers.

| Basis | Population | On time | Rate |
|---|---|---|---|
| Carrier promise (`pangea.estimated_delivery_date`) | 3,381 delivered shipments | 2,556 | **75.6%** |
| Customer request (`SORDERQ.DEMDLVDAT_0`, max per order) | 2,887 joinable deliveries | 2,429 | **84.1%** |

That is an 8.5 point spread on the same shipments. Publishing one without
naming it would be a governance failure.

Two further wrinkles:

- Only 3,381 of 3,509 shipments are delivered. 109 are `EXCEPTION` and 19 are
  `IN_TRANSIT`, and both carry a null `delivered_date`. Undelivered shipments
  are excluded from the denominator, which means the metric cannot get worse
  when a shipment fails outright — flagged as a definition risk.
- The customer-request basis is only available for the 85% of shipments that
  join to an X3 order, so switching basis also silently changes the
  denominator. `fct_shipment` therefore carries **both** flags and both promise
  dates, and the metric YAML selects between them.

**Decision taken for the POC:** carrier promise
(`var: otd_promise_basis = carrier`), because it covers 100% of delivered
shipments and needs no cross-system join. Open question 1.

---

## Needs a business rule

### Cost Per Order — computable only once someone names the cost pool

The available cost data is thinner than it looks:

- `pangea.charge` — freight and accessorials, 5.49M USD. Real, line-level.
- `paycom.earning_detail` — 9,526 rows of payroll, allocable to site and
  department via `labor_allocation_code` (`DAL-01-200` = Dallas Warehouse).
- `sage_x3.GACCENTRYD` — **only three accounts exist**: 11100 (AR), 22300
  (tax), 41000 (revenue). There is no COGS account, no expense account, and no
  AP subledger. `GACCENTRY` contains exactly one journal type: `SAL`/`SIH`.

So "fully loaded cost per order" is not computable — the general ledger in this
estate contains revenue and receivables and nothing else. A fulfillment cost
pool is computable, and a fulfillment-plus-warehouse-labour pool is computable
with an allocation basis that someone has to choose (per order? per line? per
shipped weight?).

**Decision taken for the POC:** `var: cost_per_order_pool = fulfillment` —
freight and accessorials only, allocated to the order via the shipment
reference. 2,998 of 4,200 orders (71.4%) have a matched shipment, so the metric
is reported over shipped orders only and the coverage rate is published beside
it. Status `provisional`. Open question 3.

### DSO — a days-to-pay proxy, and it should be labelled as one

Textbook DSO is `AR balance / revenue x days`, which needs an open-AR position
over time and cash application. Neither exists:

- No cash receipt, payment, or open-item table in any schema.
- `SINVOICEV.PAYDAT_0` is a single settlement date stamped on the invoice.
- 492 of 3,564 invoices (13.8%) carry the `1753-01-01` sentinel in `PAYDAT_0`,
  meaning unpaid. **An unguarded `date_diff` over the full invoice set returns
  a mean of −13,708 days** — this is landmine 2 and it lands squarely on this
  metric.

Measured on the 3,072 settled invoices: mean 48.2 days, median 45, range
28–90. The distribution is plausible and the metric is stable, but it is
*days-to-pay on settled invoices*, which is a different and more flattering
number than DSO — it structurally excludes the invoices that are late enough to
be unpaid.

**Decision taken for the POC:** publish as `dso_days_to_pay_proxy`, labelled
"DSO (days-to-pay proxy)", status `provisional`, with the 13.8% unsettled rate
published alongside it as a required companion figure. Do not label it "DSO" on
a dashboard. Open question 2.

---

## Blocked

These three get a registry entry with `status: blocked`, a populated
`blocked_reason`, and no SQL. They cost nothing and they keep the gap visible.

### Return Rate — no returns object exists

Verified absent, not merely unfound:

- `SINVOICEV.SIVTYP_0` has exactly one value: `SIN`. No credit memo type.
- Zero negative-amount lines in `SINVOICED` (0 of 9,767).
- Zero negative quantities in `SORDERQ`.
- `STOJOU.TRSTYP_0` decodes to Receipt / Issue / Adjustment / Transfer in /
  Transfer out (chapter 700). There is no return movement type, and
  `VCRTYP_0` has only `SDH`, `PTH`, `ADJ` — no return document type.
- No RMA table in any of the five schemas.

A returns process may exist in the business and simply not be captured, or it
may run outside the ERP entirely. Either way the answer comes from the client,
not from the warehouse.

### Match Rate — two of the three legs of a three-way match are missing

Three-way match needs PO, receipt, and supplier invoice.

- PO: present. `PORDER` 1,400 headers / `PORDERQ` 2,959 lines.
- Receipt: present, but **only as columns on the PO line** — `RCPQTY_0` and
  `RCPDAT_0`. 2,383 lines have a receipt quantity, 2,064 received exactly the
  ordered quantity, and 576 lines carry the sentinel receipt date.
- Supplier invoice: **does not exist**. No AP invoice table, no AP GL account
  (the only accounts are 11100/22300/41000), and no AP journal
  (`GACCENTRY.JOU_0` is `SAL` on every row).

**There is also no receipt *transaction*.** `STOJOU` holds 4,217 purchase
movements (`VCRTYP_0 = 'PTH'`), and their `VCRNUM_0` values are of the form
`PTH######` — **none of the 4,217 resolve to a `POHNUM_0`**. By contrast all
10,421 sales movements (`SDH`) resolve to a `SORDER` cleanly. So the receipt
side of the estate is weaker than "two of three legs present" suggests: a
receipt cannot be dated independently, sequenced, split across deliveries, or
attributed to a user. The PO line records only that a quantity arrived and when
the last one did.

That matters for scoping the fix. Sourcing an AP invoice alone would still not
buy a real three-way match — a receipt transaction with a PO reference is a
second, separate ask.

A two-way (PO-to-receipt) match rate *is* computable at 69.8% of lines exactly
matched on quantity. It is a different metric and it should not be shipped
under the name "Match Rate". Recorded in the registry as a note on the blocked
entry, not as a substitute.

### Inventory Accuracy — no cycle count data

Inventory accuracy is `counted quantity vs system quantity`. There is no count
table, no count document type, and no count date anywhere in the estate.

`STOJOU` adjustments (`TRSTYP_0 = 3`) are the only candidate signal: 1,008 rows,
of which 497 are negative and 511 positive, netting −11,469 units. That is a
count-adjustment *shape*, but an adjustment journal records the correction, not
the count — it cannot tell you how many locations were counted, so it has no
denominator. Any accuracy percentage built on it would be inventing the
denominator, which is worse than reporting nothing.

If the business runs cycle counts today, the data is in a spreadsheet or in
X3 count sessions that are not in this extract. Ask.

---

## Cross-cutting findings that shape the model

These came out of the same audit and are not metric-specific.

1. **CHAR padding is total, not partial.** Every row of `SORDERQ.ITMREF_0`
   (11,575), `SORDERP.ITMREF_0` (11,575), `STOJOU.ITMREF_0` (16,421) and
   `SORDER.BPCORD_0` (4,200) is padded. The master tables carry no padding at
   all. A naive equi-join returns exactly zero rows, which at least fails
   loudly. After `trim()` every one of these joins is 100% clean.

2. **`STOJOU` reconciles on the sales side and not the purchase side.** All
   10,421 shipment movements (`VCRTYP_0 = 'SDH'`) resolve to a `SORDER`; none
   of the 4,217 purchase movements (`PTH`) resolve to a `PORDER`. Any future
   `fct_inventory_movement` can attribute an issue to an order and cannot
   attribute a receipt to a purchase order. Worth confirming against the real
   X3 folder — in a live install `PRECEIPT`/`PRECEIPTD` would normally carry
   this and may simply be absent from the extract.

3. **The X3 internal joins are otherwise perfect.** `SORDERQ`→`ITMMASTER` 11,575/11,575,
   `SORDER`→`BPCUSTOMER` 4,200/4,200, `SINVOICED`→`SINVOICEV` 9,767/9,767,
   invoice line→order line 9,767/9,767, and `SORDERQ.ITMREF_0` agrees with
   `SORDERP.ITMREF_0` on all 11,575 lines. All declared grains are unique. The
   risk in this estate is entirely at the system boundaries.

4. **`pangea.shipment.customer_name` matches `BPCUSTOMER.BPCNAM_0` on 220 of
   220 distinct values.** This is not in the README join map and it is a better
   customer key for shipments than routing through the order — worth using as a
   fallback for the 15% of shipments that do not carry an order reference.

5. **Shipment reference quality**: 3,509 shipments, 247 with a null reference,
   2,998 joining cleanly to `SORDER` (85.4% of all, 91.9% of non-null), and 264
   carrying a `CUST-PO-#####` customer PO that matches nothing in X3. Padding is
   not a factor here — trimmed and untrimmed give the same 2,998.

6. **HubSpot→X3 customer matching**: exact upper-cased name gives 171/260
   (65.8%). Stripping punctuation and the legal suffix (`Inc`, `LLC`, `Ltd`,
   `Corp`, `Co`, `Group`, `Company`, `ULC`) lifts it to 182/260 (70.0%).
   `hubspot.company.domain` is truncated to 18 characters before the TLD and is
   not unique (198 distinct across 260 rows), so it is usable as corroboration
   but not as a key.

7. **HubSpot deal→ERP handoff**: 850 deals, 238 closed-won, 145 with an
   `erp_order_number`, 96 joining as-is. The 49 failures are lower-cased
   (`sous26001710`), prefix-stripped (`US25000718`), or contain two order
   numbers separated by ` / `. All three are mechanically repairable —
   `int_deal_erp_order_number` handles them and reports the lift.

8. **The Paycom roster contains duplicate people, and that is the real
   employee-identity problem.** 12 of the 150 employee rows are duplicates —
   same name, same `work_email`, different `employee_code`. So the roster
   describes 138 people, not 150.

   This matters because it breaks the two best keys at once. Name matching X3
   `REPRESENT.REPNAM_0` ("LASTNAME FIRSTNAME") to Paycom matches all 28 reps
   but returns **30 rows**. `hubspot.owner.email` matches
   `paycom.employee.work_email` exactly — 22 owners, 22 distinct emails — and
   still returns **23 rows**, because one owner hits a duplicated employee.

   Email is still the best available key; it just is not unique on the Paycom
   side, so resolution has to deduplicate within Paycom *before* matching
   across systems. That is exactly why the xref is a first-class model with a
   confidence column rather than a join buried inside a dimension.

9. **Site codes need a crosswalk in both directions.** X3 `US001/US002/CA001`,
   Paycom `DAL-01/RNO-01/TOR-01`, Netstock uses the X3 codes directly (clean).
   The crosswalk is a seed, not derived logic.

10. **Currency is genuinely multi.** 3,512 USD and 688 CAD orders; 2,993 USD and
   571 CAD invoices. The only FX signal in the estate is the implied rate in
   `GACCENTRYD` (`AMTLOC_0 / AMTCUR_0`), which is **0.7400 for CAD on 1,690 of
   1,713 lines**, with the remainder within ±0.0002 of rounding. That is a
   single fixed rate, not a rate table — real reporting will need a proper rate
   source. Open question 10.

11. **Netstock is stale and slightly orphaned**: `last_sync_at` is 2026-09-02
    on every row, and 35 of 896 item-locations (3.9%) reference items with no
    `ITMMASTER` row.

12. **Paycom has no change tracking**, so its ingestion pattern is full refresh
    while X3 (`UPDTICK_0`) and HubSpot (`hs_lastmodifieddate`) both support
    incremental. That asymmetry belongs in the ingestion design, not the model.

13. **Tracking event ordering**: 316 of 24,504 events (1.29%) have a timestamp
    earlier than the previous event by sequence. Milestone extraction uses
    `event_code`, never `min(event_ts)`.
