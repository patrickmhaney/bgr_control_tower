# Open questions

Ten questions the POC could not answer from the data. **None of them blocked
the build.** Each one has a documented assumption, the assumption is encoded as
a `var` in `dbt_project.yml` or as a field in the metric registry, and the
answer changes a config value rather than a model.

The "cost to reverse" column is the honest estimate of what changes if the
business answers differently than we assumed.

| # | Question | Assumed for the POC | Cost to reverse |
|---|---|---|---|
| 1 | On-Time Delivery promise basis | Carrier promise date | One var |
| 2 | DSO basis | Days-to-pay proxy | One metric definition |
| 3 | Cost Per Order cost pool | Fulfillment only | One var + possibly a fact |
| 4 | Fiscal calendar | Fiscal = calendar year | `dim_date` rebuild |
| 5 | Semantic layer tool | Tool-neutral YAML + generator | None — that is the point |
| 6 | Power BI model topology | One shared semantic model | Rollout, not code |
| 7 | Customer survivorship | X3 financial, HubSpot firmographic | One model |
| 8 | Metric ownership | Unassigned, roles proposed | Registry field |
| 9 | What Pangea actually is | Freight visibility platform | Re-cut one source |
| 10 | Currency policy | Report in USD at a derived rate | One var |
| 11 | As-was vs as-is-today attribution | Type 1 throughout | **Unrecoverable, and rising** |
| 12 | Can one order ship more than once? | One shipment per order | One metric model |
| 13 | Is the Pangea customer name typed or system-populated? | A reliable key | Customer attribution falls to 85.4% |

---

## 1. On-Time Delivery — against which promise?

**The finding.** Both candidate dates exist and they disagree by 8.5 points on
the same shipments: 75.6% against the carrier's promised delivery date, 84.1%
against the customer's requested delivery date. The two also have different
denominators — the carrier date is present on all 3,381 delivered shipments,
the customer date only on the 2,887 that join back to an X3 order.

**Assumed.** Carrier promise (`pangea.estimated_delivery_date`).
`var: otd_promise_basis = carrier`.

**Why.** Full coverage, no cross-system join, and it is the number the carrier
can be held to. It is also the more conservative of the two.

**What we need.** Whether the dashboard audience is Operations (who manage
carriers, and want the carrier number) or Sales/Customer Service (who face the
customer, and want the customer number). If the answer is "both", that is two
metrics with two names, not one metric with an argument — and the model already
supports it: `fct_shipment` carries `is_on_time_vs_carrier_promise` and
`is_on_time_vs_customer_request` side by side.

**Second-order question nobody has asked yet.** 109 shipments are in
`EXCEPTION` status with no delivery date, and 19 are still in transit. They are
currently excluded from the denominator, which means **a shipment that fails
completely cannot hurt the metric**. That is usually not what the business
wants.

Measured, so the decision can be made against the number rather than in the
abstract:

```
current  (undelivered excluded)   2,556 / 3,381  =  75.6%
counted  (undelivered = late)     2,556 / 3,509  =  72.8%
                                                    -2.8 pts

3,381 DELIVERED  ·  109 EXCEPTION  ·  19 IN_TRANSIT
```

An operations VP will have an immediate opinion about 2.8 points. Put both on
the slide and the decision takes two minutes rather than a follow-up meeting.
Options: count undelivered-past-promise as late, or publish a separate
completion rate beside the metric.

## 2. DSO — true AR-based, or the days-to-pay proxy?

**The finding.** There is no cash application data anywhere in the five source
systems, and no open-AR position over time. Textbook DSO is not computable.
What exists is `SINVOICEV.PAYDAT_0`, a single settlement date per invoice,
giving a mean 48.2 / median 45 days to pay on the 86.2% of invoices that are
settled.

**Assumed.** Publish the proxy under the name `dso_days_to_pay_proxy`, label
"DSO (days-to-pay proxy)", status `provisional`, with the 13.8% unsettled rate
as a mandatory companion figure.

**Why.** The proxy is directionally useful and cheap. Labelling it "DSO" is
not, because it structurally excludes exactly the invoices that make DSO bad —
the unpaid ones. A finance audience will compare it to a benchmark and the
comparison will be wrong.

**What we need.** Either (a) accept the proxy under its honest name, or (b)
source the AR subledger — open items, cash receipts, and application — which is
a new extract, not a modelling change. If (b), the metric becomes a genuine
balance-and-flow calculation and needs a periodic AR snapshot fact.

## 3. Cost Per Order — which cost pool, and what allocation basis?

**The finding.** The GL in this estate contains three accounts — AR, tax, and
revenue — and one journal type. There is no COGS, no expense, no AP. "Fully
loaded" is not computable from the sources we have. What is computable:
freight and accessorials from Pangea (5.49M USD, line level), and warehouse
labour from Paycom, allocable to site and department via `labor_allocation_code`.

**Assumed.** `var: cost_per_order_pool = fulfillment` — freight and
accessorials only, attached to the order through the shipment reference,
reported over shipped orders only (2,998 of 4,200 = 71.4%) with the coverage
rate published beside the metric. Status `provisional`.

**What we need.** Three things, in order:
1. Which pool. Fulfillment only, fulfillment + warehouse labour, or fully
   loaded (which requires a GL extract we do not have).
2. If labour is included, the allocation basis: per order, per line, per
   shipped weight, or per pick. Each gives a different answer and each is
   defensible.
3. Whether unshipped orders belong in the denominator. Currently they do not.

## 4. Fiscal calendar

**The finding.** Not derivable. Nothing in the sources indicates a fiscal
period structure — `GACCENTRY.ACCDAT_0` is a plain date and there is no period
or year-close table.

**Assumed.** Fiscal year = calendar year, months = calendar months, quarters =
calendar quarters. `var: fiscal_year_start_month = 1`.

**Why it matters more than it looks.** `dim_date` is the one dimension every
metric touches. A 4-4-5 or 5-4-4 retail calendar, or a fiscal year starting in
a month other than January, changes every period-over-period comparison on all
nine dashboards. `dim_date` is built to take a start month as a var, so a
simple offset is cheap; a 4-4-5 calendar needs a period definition table from
Finance and is not cheap.

**What we need.** From Finance: fiscal year start month, period structure
(calendar months vs 4-4-5 vs 13-period), and whether the two legal entities
share a calendar.

## 5. Semantic layer tool

**The finding.** Three viable options, evaluated in `docs/architecture.md`.

**Assumed.** Neither, yet — and deliberately. The POC keeps the metric registry
in tool-neutral YAML (`semantic/metrics/*.yml`) and generates the tool-specific
artefacts from it: dbt semantic models, Cube schema, and Power BI TMDL/DAX. The
spike (Phase 3) proved this works end to end.

**Why.** The tool choice has a long procurement tail and the POC should not
wait on it. Making the registry the source of truth means the decision costs a
generator target, not a rewrite. The recommendation remains dbt semantic models
for governance if no AI-serving requirement lands, Cube if one does.

**What we need.** Whether an AI agent needs to query metrics over an API in
production (Cube), or whether governance and lineage inside the dbt project is
the whole requirement (dbt). And whether dbt Cloud is on the table — the hosted
Semantic Layer API is the piece dbt-core cannot give you.

**Two qualifications on "tool-neutral", because they are findable.**

*Neutrality is bounded by a declared grammar, and that grammar is now closed.*
Filters were originally raw SQL strings translated to DAX by a parser, which
made portability hold only as far as the parser coped — and it silently
mistranslated `>=`. Filters are now structured triples (`column`, `op`,
optional `value`) over a fixed op set: `is_true`, `is_false`, `is_null`,
`is_not_null`, `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`. Each renderer maps
the op to its own dialect from a table, so there is no parsing and a
translation bug is unrepresentable rather than guarded against. A metric
needing something outside that set is a compiler change — but the set is
written down, which is the difference between a bounded claim and a vague one.

*MetricFlow cannot express every metric.* `customer_unmatched_rate` has no
aggregation time dimension on its base model, which MetricFlow requires, so it
is absent from the generated semantic models. The generated file names it in
its header and the compiler prints it on every run. That is a limitation of one
target rather than of the registry — the same metric compiles correctly to DAX
and to Cube — and it is exactly the argument for keeping the registry neutral.

## 6. One Power BI semantic model or nine?

**The finding.** The nine processes share dimensions and facts heavily. Nine
independent models means nine definitions of "customer" and nine chances for
revenue to disagree between dashboards.

**Assumed.** One shared import-mode semantic model over the conformed core,
nine reports against it, per-process display folders or perspectives to keep
each report's field list manageable.

**Why.** It is the only topology where "one metric, two dashboards, one number"
is structurally guaranteed rather than maintained by discipline. A star schema
also outperforms wide flat tables in VertiPaq — the flat-table instinct is a
holdover from tools that could not handle relationships.

**What we need.** This is an ownership and rollout question, not a technical
one. One model means one deployment pipeline, one refresh schedule, one set of
RLS rules, and one team that owns changes to it. If the nine dashboards have
nine owners who each want to ship independently, that tension needs resolving
before the model is built, not after.

## 7. Customer survivorship between X3 and HubSpot

**The finding.** No shared key. Exact upper-cased name matches 171 of 260
HubSpot companies (65.8%); normalising punctuation and legal suffixes lifts it
to 182 (70.0%). `hubspot.company.domain` is truncated to 18 characters and is
not unique (198 distinct values across 260 rows), so it corroborates but cannot
key. **Roughly 30% of HubSpot companies will not match anything in X3** and
that number is a governance finding, published as a data quality metric, not
something to bury.

**Assumed.** `int_customer_xref` emits one row per match candidate with
`match_method` and `confidence`. `dim_customer` survives X3 for financial
attributes (credit limit, payment terms, currency, accounting code) and HubSpot
for firmographics (industry, employee count, annual revenue, domain).

**What we need.** Confirmation of the survivorship rule, and a decision on the
unmatched: are unmatched HubSpot companies prospects (correctly absent from
X3), or are they real customers with a name mismatch that needs stewardship? A
sample of 20 would settle it.

## 8. Metric ownership

**The finding.** The registry requires an owner per metric and there is no
source of truth for who that is.

**Assumed.** `owner: TBD` on every metric, with a proposed role in
`owner_proposed` (Finance for DSO, Operations for the shipment metrics,
Sales Operations for Cost Per Order). The registry test asserts the field is
present, not that it is filled — so this stays visible rather than quietly
resolving to nobody.

**What we need.** A named person per metric who signs off on the definition and
approves changes to it. Without that, "one definition per metric" is a file
layout, not governance.

## 9. What is Pangea?

**The finding.** The product identity is a guess — the whiteboard was cut off
at "Pange…". The schema is modelled as a generic freight/parcel visibility
platform, and the data is internally consistent with that reading: SCAC-keyed
carriers, PARCEL/LTL/TL modes, tracking events, accessorial charges.

**Assumed.** It is a freight visibility platform, and `pangea.shipment` is the
shipment fact.

**Impact if wrong.** Two of the four buildable metrics (On-Time Delivery, Cost
Per Shipment) sit entirely on this source, and a third (Cost Per Order) depends
on it for the cost pool. If Pangea turns out to be something else — a WMS, a
TMS with a different grain, a customs broker — the shipment grain probably
survives but the cost semantics may not.

**Worth noting**: `pangea.shipment.customer_name` matches
`BPCUSTOMER.BPCNAM_0` on all 220 distinct values, which the README's join map
does not mention. Whatever Pangea is, it is being fed customer names from X3.

## 10. Currency policy

**The finding.** Genuinely multi-currency: 3,512 USD / 688 CAD orders, 2,993
USD / 571 CAD invoices. There is no FX rate table. The only rate signal in the
estate is implied by `GACCENTRYD.AMTLOC_0 / AMTCUR_0`, which is **0.7400 for
CAD on 1,690 of 1,713 lines**, the remainder within ±0.0002 of rounding. That
is a single fixed rate applied at posting, not a rate series.

**Assumed.** Report in USD. `int_fx_rate` derives the rate per document
currency per month from the GL, so the model is shaped for a real rate series
even though today it returns a constant. Every monetary column in the marts
carries both a document-currency and a reporting-currency variant, suffixed
`_doc` and `_usd`.

**What we need.** Whose rates (corporate budget rate, month-end spot, daily
spot?), as of what date (transaction date, invoice date, period close?), and
whether dashboards need to be re-statable at a different rate after the fact.
The last one is the expensive answer — it means storing rates as a dimension
and computing conversion at query time rather than at load.

**And one sub-question that decides whether the mechanism works at all: does
each legal entity post `AMTLOC_0` in its own local currency, or in the
reporting currency?**

The derived rate is `sum(AMTLOC_0) / sum(AMTCUR_0)` across the GL, which
recovers a document-to-**company**-currency rate. That is the rate we want only
where company currency equals reporting currency. In this extract it does —
GLBCA posts `AMTLOC_0` in USD at 0.74 — but that is unusual for a Canadian
legal entity, and the mock's `COMPANY` table carries no currency column to
check it against:

```
CPY_0    CUR_0   sum(AMTCUR_0)   sum(AMTLOC_0)   implied
GLBCA    CAD      80,681,697      59,704,456      0.74
GLBUS    USD     416,627,241     416,627,241      1.00
```

In a real X3 folder a Canadian entity posts `AMTLOC_0` in CAD, the ratio
becomes 1.00, and **26.4M of CAD revenue reports as USD with a green build**.

Two things are already in place against that. `COMPANY.CUR_0` is on the
extraction list in `ingestion/config.py` with a note explaining why, so the
column arrives with the real folder. And
`tests/assert_fx_rate_is_not_identity_for_foreign_currency.sql` fails if any
non-reporting currency resolves to exactly 1.0, which is the symptom — it
catches the failure even without the column. When the column arrives, restrict
`int_fx_rate` to entities whose company currency is the reporting currency.

A five-minute check against the production folder decides whether 26.4M
converts or does not.

---

## 11. As-was attribution, or is as-is-today acceptable?

**The finding.** All five conformed dimensions are Type 1 — current state only.
The facts span Jul 2024 to Aug 2026, so today's sales rep, payment terms,
credit limit, customer group and ABC class are attributed to two years of
history. "Cost per shipment by rep" currently means "by whoever owns that
customer *now*". No source system in the estate carries effective dating on
customer, rep or item-planning attributes, so history cannot be reconstructed
retrospectively from any of them.

**Assumed.** Type 1 throughout. Historical facts carry today's attributes.

**Why.** No active metric slices by an attribute known to churn, and Type 2 on
five dimensions is real cost for a POC.

**What we need.** Whether any of the nine dashboards has to answer "who owned
this account *at the time*". Commission, territory performance and rep
scorecards all do. If yes, that is a Type 2 dimension and a snapshot process.

**Cost to reverse. Unrecoverable, and rising — this is the one open question
that is not a config change.** A Type 2 dimension can only be built forward
from its first snapshot. Deferring the decision does not defer the cost; it
deletes the history the decision would need.

**Already done, regardless of the answer.** `dbt snapshot` now runs on
`stg_sage_x3__bpcustomer`, `stg_sage_x3__represent` and
`stg_netstock__item_location`. Three models, nothing consumes them, and they
cost one command in the schedule. They buy the option: if the answer is "yes,
we need as-was", history accumulates from today rather than from the day
someone asks.

---

## 12. Does a sales order ever ship in more than one shipment?

**The finding.** Never, in this extract: every one of the 2,998 shipments that
resolves to an X3 order is the only shipment on that order. Two things rest on
that and neither was stated anywhere — the shipment-to-order link is treated as
1:1, and `cost_per_order`'s denominator (`count distinct sales_order_number`)
is only safe over a pre-aggregation because an order cannot span two ship
dates.

**Assumed.** One shipment per order. Cost Per Order is stated as cost per
*shipped* order.

**What we need.** Whether production splits orders across shipments —
backorders, multi-site fulfilment, partial releases. Partial and split
shipments are ordinary in freight, so the honest expectation is that this
assumption does not survive contact with real data.

**Cost to reverse.** One metric model. The risk was never the fix; it was that
nothing failed when the assumption broke. That is now covered from two sides:
`ask_metric.py` computes non-re-aggregatable metrics against the base fact
rather than summing a pre-aggregate, and `scripts/test_metric_parity.py`
reconciles every metric both ways on each build. Cost Per Order currently
agrees between the two paths *because* no order ships twice; the day one does,
the divergence appears in the parity output rather than in a dashboard.

---

## 13. Is `pangea.shipment.customer_name` system-populated or typed?

**The finding.** It matches `BPCUSTOMER.BPCNAM_0` on all 220 distinct values,
and zero ERP customer names collide. This link is not in the source README's
join map, and it is what recovers the customer for the 511 shipments (14.6%)
carrying no resolvable order reference — the reason customer resolution reaches
100% while order resolution stops at 85.4%.

**Assumed.** The name is a reliable key. `int_shipment_order` falls back to it
and `fct_shipment` reports 100% customer resolution.

**What we need.** How the field is populated in the real platform. If an
integration writes it from the ERP, it is a reliable key and belongs on the
join map as a solid line. If a broker or a user types it at booking, it is a
fuzzy match wearing an exact match's clothes. And separately: whether ERP
customer names are unique in the production folder, which a two-company mock
cannot establish.

**Cost to reverse.** If the name proves unreliable, customer attribution on
shipments falls from 100% toward the 85.4% order-reference rate, and every
customer slice of On-Time Delivery and Cost Per Shipment loses that much of its
denominator.

**Exposure is measurable the day real data lands.** `fct_shipment` publishes
`customer_resolution_method`, `int_shipment_order` now carries
`customer_name_match_count` and `customer_name_is_ambiguous` rather than
silently taking the first match, and
`tests/assert_customer_names_are_unique.sql` fails if two ERP customers ever
share a name.

---

## Assumptions that were never questions

Recorded here because they are decisions, and undocumented decisions become
folklore.

- **Shipment cost basis.** `sum(charge.amount_usd)`, not
  `shipment.total_cost_usd`. The header exceeds the charge lines by 9.9% in
  aggregate and not one of the 3,509 shipments agrees to the cent. Line-level cost
  is auditable and decomposable; a header number nobody can explain is not
  governable. `var: shipment_cost_basis`. The variance is published on
  `fct_shipment` as `cost_variance_usd` rather than hidden.
- **Milestone extraction from tracking events uses `event_code`, never
  `min(event_ts)`.** 1.29% of events are out of sequence relative to
  `event_seq`, and the README is explicit that the earliest timestamp is not
  reliably the pickup.
- **Archived HubSpot records are flagged, not filtered**, in staging. The mart
  decides. Currently `dim_customer` excludes archived companies from
  firmographic survivorship but keeps them in the xref so the match rate is
  honest.
- **X3 array columns (`REP_0`/`REP_1`) are not unpivoted in the core.** The
  primary rep owns the row. `REP_1` is carried as an attribute. Unpivoting
  would double-count commission, and no active metric needs the secondary rep.
  Revisit when an H2R or commission metric lands.
- **Netstock is a snapshot, not an SCD.** It is regenerated wholesale each sync
  and carries a single `last_sync_at` (2026-09-02). Modelling it as a slowly
  changing dimension would be inventing history that the source does not have.
