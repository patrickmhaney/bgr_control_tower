# Metric feasibility audit

Every number below was measured against `mock_sources.duckdb` (SEED 20260905),
not inferred. The queries are reproducible from `scripts/profile_sources.py`.

**Headline: all seven defined metrics now compute, but five of them carry a
business decision that has not been made.** Three were blocked in the original
audit — not because they were hard, but because the documents they measure
were absent from the extract. Sourcing those documents unblocked them without
a single change to the compiler or the metric grammar.

> **Read the next paragraph before quoting any of this to the client.**
>
> This audit measures `mock_sources.duckdb`. That file is a *model* of five
> source systems, not a sample of them. When the original version of this
> document said "no returns object exists in any of the five source systems",
> the true statement was "the generator did not write one" — and the mock
> carries 22 X3 tables where a live folder carries two to four thousand.
> Sage X3 has sales returns, purchase receipts, supplier invoices and a
> physical-inventory module as standard. The blockage was in the mock.
>
> What the audit *does* establish, and what remains worth saying, is the shape
> of each metric: what it needs, what decisions it hides, and what it costs to
> get wrong. Those survive contact with the real folder. The row counts do not.

| Metric | Process | Verdict | Registry status |
|---|---|---|---|
| Cost Per Shipment | I2D | Computable | `active` |
| On-Time Delivery | I2D | Computable, but "on time against what?" is unanswered | `active` (assumption flagged) |
| Cost Per Order | O2C | Needs an allocation rule | `provisional` |
| DSO | O2C | Proxy only — no cash application data exists | `provisional` |
| Return Rate | O2C | Computable once returns are sourced; denominator and date basis both open | `provisional` |
| Match Rate | S2P | Computable once receipts and AP invoices are sourced; tolerance policy open | `provisional` |
| Inventory Accuracy | I2D | Computable once count sessions are sourced; tolerance and basis open | `provisional` |

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

**Decision taken for the POC:** carrier promise (the metric filters on
`is_on_time_vs_carrier_promise`), because it covers 100% of delivered
shipments and needs no cross-system join. Open question 1.

---

## Needs a business rule

### Cost Per Order — computable only once someone names the cost pool

The available cost data is thinner than it looks:

- `pangea.charge` — freight and accessorials, 5.49M USD. Real, line-level.
- `paycom.earning_detail` — 9,526 rows of payroll, allocable to site and
  department via `labor_allocation_code` (`DAL-01-200` = Dallas Warehouse).
- `sage_x3.GACCENTRYD` — **five accounts exist**: 11100 (AR), 21000 (AP),
  22300 (tax), 41000 (revenue), 50000 (purchases). `GACCENTRY` carries two
  journals: sales (`SAL`, invoices and credit memos) and purchasing (`PUR`).
  There is no COGS account, no operating expense and no payroll posting.

So "fully loaded cost per order" is not computable — the general ledger in this
estate holds sales, receivables and purchasing, and no cost of fulfilment or
overhead. A fulfillment cost
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
- 523 of 3,691 invoice documents (14.2%) carry the `1753-01-01` sentinel in
  `PAYDAT_0`, meaning unpaid — 492 of the 3,564 invoices and 31 of the 127
  credit memos. **An unguarded `date_diff` over the full set returns a mean of
  about −14,000 days** — this is landmine 2 and it lands squarely on this
  metric.

Measured on the 3,168 settled documents: mean 47.7 days, median 45, range
21–90. The metric itself, at invoice-line grain, is 48.0 days. The
distribution is plausible and the metric is stable, but it is
*days-to-pay on settled invoices*, which is a different and more flattering
number than DSO — it structurally excludes the invoices that are late enough to
be unpaid.

**Decision taken for the POC:** publish as `dso_days_to_pay_proxy`, labelled
"DSO (days-to-pay proxy)", status `provisional`, with the 13.8% unsettled rate
(13.8% of invoice lines) published alongside it as a required companion figure.
Do not label it "DSO" on
a dashboard. Open question 2.

---

## Unblocked by sourcing the missing documents

Each of these was blocked on a document that did not exist in the extract.
Adding it changed nothing about how the metric is defined or compiled — the
grammar and the compiler were untouched. That is the result worth reporting:
the cost of a new metric here is a source and a definition, not an
architecture.

### Return Rate — needed a returns object

**What was missing.** No return document, no credit-memo invoice type, no
return movement type in the stock journal, no RMA table.

**What was added.** `SRETURN` / `SRETURND` as the return document, a `SCR`
credit-memo type on the sales invoice tables with the sign reversed, and
`TRSTYP_0 = 6` movements putting the stock back on the shelf. Returns raise
credit memos, credit memos post to the GL, and invoiced revenue still
reconciles to account 41000 — the existing test proves it.

**Measured.** 146 returns / 179 lines against 3,564 invoices. Returned value
$2.78M against $218.9M invoiced: **1.27%**.

**What is still open.** Two things, and they move the number more than the
data does.

- *The denominator.* Invoiced value is used. Ordered value and shipped value
  are both computable and all three differ, because an order can be invoiced
  in part. Open question 16.
- *The date.* A return raised in March against a January order lands in
  January on this metric, because the denominator has no other date. So it
  answers "what fraction of what we sold that month came back", not "how much
  came back this month". Both are legitimate and they are not close to each
  other on a monthly chart. Open question 17.

Two source properties are carried rather than cleaned away: 8% of returns
arrive with an order reference that resolves to nothing (blank or lowercased),
and 14% have not been credited at extract time — so any recent month's rate
rises as credits post.

### Match Rate — needed a receipt and a supplier invoice as documents

**What was missing.** The purchase order existed. The receipt existed only as
`RCPQTY_0` / `RCPDAT_0` denormalised onto the PO line, so it could not be
dated, sequenced, split across deliveries or attributed to a user. The
supplier invoice did not exist at all, and neither did an AP account or an AP
journal.

**What was added.** `PRECEIPT` / `PRECEIPTD` and `PINVOICE` / `PINVOICED`, an
AP journal (`PUR` / `PIH`) and accounts 21000 and 50000. The stock journal's
purchase movements now carry receipt numbers that resolve — previously all
4,217 of them resolved to nothing, which is the single fact that made a
three-way match impossible.

**Measured.** 2,498 invoice lines across 1,186 invoices. **70.7% matched.**

| Result | Lines | Share |
|---|---:|---:|
| `matched` | 1,766 | 70.7% |
| `price_variance` | 295 | 11.8% |
| `quantity_variance` | 274 | 11.0% |
| `not_received` | 107 | 4.3% |
| `no_purchase_order` | 56 | 2.2% |

The reason is kept on the fact, not just the flag. A match rate says there is
a problem; `match_result` says which desk to send it to. `no_purchase_order`
is maverick spend — a governance finding rather than a data quality one.

**One modelling decision worth knowing about.** An invoice line is compared to
the receipt *it names*, not to every receipt against the PO line. 514 lines
here are multi-delivery, and comparing each invoice to the cumulative received
quantity reports a variance on both halves of a perfectly good transaction —
it moved the measured rate from 59.2% to 70.7%. This is exactly the class of
error a three-way match implementation gets wrong quietly.

**What is still open.** The tolerance policy. Exact quantity and 2% price is
assumed; AP departments commonly allow a quantity band too, which would move
this several points. Until AP sets one, the rate measures the policy as much
as the process. Open question 14.

### Inventory Accuracy — needed a count session, not an adjustment journal

**What was missing.** No count table, no count document type, no count date.
The stock journal's adjustments looked like the right signal and were not: an
adjustment records the correction, not the count, so it can say how much was
wrong but not how much was checked. It has no denominator, and inventing one
produces something that looks like a measurement.

**What was added.** `STOCOUNT` / `STOCOUNTD` — monthly cycle-count sessions per
site, carrying `QTYTHEO_0` (the system quantity *at count time*) beside
`QTYCNT_0`. Variances now post as adjustments carrying the session number, so
the stock journal reconciles to the counts instead of being noise.

**Measured.** 78 sessions, 2,843 counted positions, 2,656 accurate:
**93.4%**.

**What is still open.** Two decisions and one verification.

- *The tolerance band.* Zero is assumed — accurate only on an exact match.
  Many warehouses allow a quantity or value band. Open question 15.
- *The basis.* Accuracy is by position. A site that miscounts one pallet of
  5,000 and gets 400 other positions right scores 99.75% here and far worse on
  a unit or value basis.
- *The table names.* `STOCOUNT` / `STOCOUNTD` are **constructed**. The counting
  mechanism is right; the names must be checked against the client's folder,
  like `APLSTD`.

One property of this metric deserves its own line, because it is the only
irreversible thing in this document: `QTYTHEO_0` is the system quantity at the
moment of the count and cannot be reconstructed later from stock on hand. If
the count tables are not captured, inventory accuracy cannot be rebuilt
retrospectively at any price.

---

## Cross-cutting findings that shape the model

These came out of the same audit and are not metric-specific.

1. **CHAR padding is total, not partial.** Every row of `SORDERQ.ITMREF_0`
   (11,575), `SORDERP.ITMREF_0` (11,575), `STOJOU.ITMREF_0` (14,226) and
   `SORDER.BPCORD_0` (4,200) is padded. The master tables carry no padding at
   all. A naive equi-join returns exactly zero rows, which at least fails
   loudly. After `trim()` every one of these joins is 100% clean.

2. **`STOJOU` reconciles on both sides.** All 10,421 shipment movements
   (`VCRTYP_0 = 'SDH'`) resolve to a `SORDER`, and all 2,664 receipt movements
   (`PTH`) resolve to a `PRECEIPT`. Before the receipt documents were sourced,
   none of the purchase movements resolved to anything — worth checking first
   against the real X3 folder, because it decides whether a three-way match is
   possible at all.

3. **The X3 internal joins are otherwise perfect.** `SORDERQ`→`ITMMASTER` 11,575/11,575,
   `SORDER`→`BPCUSTOMER` 4,200/4,200, `SINVOICED`→`SINVOICEV` 9,923/9,923,
   invoice line→order line 9,767/9,767 (the 156 credit-memo lines carry no
   order line), and `SORDERQ.ITMREF_0` agrees with `SORDERP.ITMREF_0` on all
   11,575 lines. All declared grains are unique. The one exception is the
   hand-keyed return reference above. Otherwise the risk in this estate is
   entirely at the system boundaries.

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

10. **Currency is genuinely multi.** 3,512 USD and 688 CAD orders; 3,102 USD and
   589 CAD invoice documents. The only FX signal in the estate is the implied
   rate in `GACCENTRYD` (`AMTLOC_0 / AMTCUR_0`), which is **0.7400 for CAD on
   1,737 of 1,767 lines**, with the remainder within rounding. That is a
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
