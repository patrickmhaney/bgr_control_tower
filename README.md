# Mock source systems for the Globex data warehouse build

A single DuckDB file containing five mock source schemas, ~233,000 rows, covering
Jul 2024 – Aug 2026. Built for design exploration: profiling, grain discovery,
conformed-dimension planning, and finding out where the joins break.

```bash
pip install duckdb
duckdb mock_sources.duckdb        # CLI
```
```python
import duckdb
con = duckdb.connect("mock_sources.duckdb", read_only=True)
con.sql("SELECT * FROM sage_x3.SORDER LIMIT 5")
```

Everything is seeded (`SEED = 20260905`), so re-running the generator reproduces
the same data exactly.

**Looking for the pictures?** [`docs/atlas.md`](docs/atlas.md) is all 17 pipeline
and data-model diagrams on one page, captioned. GitHub renders them inline.
[`docs/README.md`](docs/README.md) indexes the rest of the documentation.

---

## 1. Fidelity — read this before you trust anything

| Schema | Fidelity | What it's based on |
|---|---|---|
| `sage_x3` | **High** | Real X3 naming conventions: `_0` suffixes, array columns (`_1`, `_2`), `UPDTICK_0` optimistic-lock counters, CHAR padding, SQL Server sentinel dates, integer local menus, no enforced FKs. Table and column *names* are close but not guaranteed complete — validate against the client's folder before writing production DDL. |
| `hubspot` | **High** | Shaped like a Fivetran/Airbyte landing, which is how you'd actually get it. Properties arrive as strings, associations are a separate many-to-many, `archived` instead of hard deletes. |
| `paycom` | **Low by nature** | Paycom has no queryable backend and a thin API. This is modeled as **flat report exports**, which is the real constraint. Dates are `MM/DD/YYYY` strings, amounts are strings. |
| `netstock` | **Inferred** | Grain and column semantics are right (item × location, forecast periods, ABC/XYZ, ROP). Exact names are my construction. |
| `pangea` | **Inferred, and the product is a guess** | The whiteboard was cut off at "Pange…". This is modeled as a generic freight/parcel visibility platform. Tell me what it actually is and I'll re-cut it. |

Two things to note in `sage_x3`: the local-menu table is named `APLSTD` here, and
you should verify that name against the install — the mechanism (integer enums
resolved through a menu table plus `ATEXTRA` for translations) is right even if
the table name isn't. And `ITMDES1_0` in `SORDERP` is denormalized at
order time, so it drifts from `ITMMASTER` — that's real X3 behavior, not a bug here.

---

## 2. Table inventory and grain

**`sage_x3`** — ERP
| Table | Grain |
|---|---|
| `COMPANY`, `FACILITY` | Legal entity / site. Two companies (US + CA), three sites. |
| `BPARTNER` | One row per business partner; `BPCFLG_0`/`BPSFLG_0` flag customer vs supplier. |
| `BPCUSTOMER`, `BPSUPPLIER` | Role-specific extension of `BPARTNER`. |
| `BPADDRESS` | Partner × address code. Multiple ship-tos per customer. |
| `ITMMASTER` | Item. |
| `ITMFACILIT` | **Item × site** — replenishment policy, safety stock, lead time. |
| `SORDER` | Sales order header. |
| `SORDERQ` / `SORDERP` | Order **line**, split across two tables: quantities in Q, prices in P. Join on `SOHNUM_0 + SOPLIN_0`. |
| `SINVOICEV` / `SINVOICED` | Invoice header / line. Line carries `SOHNUM_0` back to the order. |
| `STOCK` | Item × site × lot × location, current on-hand. |
| `STOJOU` | Stock movement (transaction-level). Your inventory fact source. |
| `PORDER` / `PORDERQ` | Purchase order header / line, with expected vs actual receipt dates. |
| `GACCENTRY` / `GACCENTRYD` | GL journal header / line. |
| `REPRESENT` | Sales rep. |
| `APLSTD`, `ATEXTRA` | Local-menu labels and translations. |

**`hubspot`** — `company`, `contact`, `deal`, `deal_stage_history`, `association`,
`engagement`, `owner`, `pipeline_stage`.

**`paycom`** — `employee`, `check`, `earning_detail`, `deduction_detail`,
`tax_detail`, `gl_mapping`. Check grain is one row per employee per pay period
(biweekly); detail tables are one row per check per code.

**`netstock`** — `item_location`, `forecast` (item × location × month),
`forecast_accuracy`, `replenishment_recommendation`, `supplier`.

**`pangea`** — `shipment`, `shipment_leg`, `tracking_event` (event-level),
`charge`, `carrier`.

---

## 3. Cross-system join map

This is the part that matters for your design. Solid lines are reliable keys;
dashed lines are the ones that will eat your sprint.

```
                        sage_x3.ITMMASTER
                          ITMREF_0  ────────────  netstock.item_location.item_code
                             │                     (clean, but 35 orphans)
                             │
        sage_x3.SORDERQ.ITMREF_0 (CHAR-padded — needs trim)
                             │
                             │
  hubspot.deal ─ ─ ─ ─►  sage_x3.SORDER  ─ ─ ─ ─►  pangea.shipment
   erp_order_number         SOHNUM_0              reference_number
   (40% clean match)                              (85% clean match)
        │                       │
        │                       │ BPCORD_0 (CHAR-padded)
        │                       ▼
        │                sage_x3.BPCUSTOMER
        └ ─ ─ ─ ─ ─ ─ ─ ─►  (NO KEY — name only,
   hubspot.company.name       and names have drifted)

  sage_x3.REPRESENT.REPNAM_0  ─ ─ ─ ─►  paycom.employee (first+last name only)
  sage_x3.FACILITY.FCY_0      ─ ─ ─ ─►  paycom.employee.location_code
                                          (US001 → DAL-01, etc. — needs a map)
  paycom.gl_mapping.gl_account ────────►  sage_x3.GACCENTRYD.ACC_0
  netstock.item_location.location_code ─►  sage_x3.FACILITY.FCY_0  (clean)
```

**The four decisions this data is meant to force:**
1. What is your conformed customer? There is no shared key between HubSpot and X3.
   You need a matching strategy (name + domain + fuzzy) and a survivorship rule.
2. What is your conformed employee/rep? Paycom and X3 share only names.
3. Is `pangea.shipment` a fact or a dimension-ish event stream? `tracking_event`
   is a much better fit for a shipment-milestone fact than the header is.
4. Do you land Netstock forecasts as a snapshot fact (they're regenerated
   wholesale each sync, `last_sync_at = 2026-09-02`) or as an SCD?

---

## 4. Deliberate landmines

Each of these is real behavior from the corresponding system. Verified present:

1. **CHAR padding in X3.** `SORDERQ.ITMREF_0`, `SORDERP.ITMREF_0`,
   `STOJOU.ITMREF_0` and `SORDER.BPCORD_0` are space-padded; the master tables
   are not. A naive equi-join returns **zero rows**.
   ```sql
   SELECT count(*) FROM sage_x3."SORDERQ" q JOIN sage_x3."ITMMASTER" m
     ON q."ITMREF_0" = m."ITMREF_0";              -- 0
   SELECT count(*) FROM sage_x3."SORDERQ" q JOIN sage_x3."ITMMASTER" m
     ON trim(q."ITMREF_0") = m."ITMREF_0";        -- 11,575
   ```
2. **Sentinel dates.** `1753-01-01` means "no date", not 1753. Present in
   `SORDER.SHIDAT_0` (402), `SINVOICEV.PAYDAT_0` (492), `PORDERQ.RCPDAT_0` (576).
   Any `datediff` that doesn't filter these will produce a ~99,000-day average.
3. **Split line tables.** Quantity and price live in different tables and both
   carry `ITMREF_0`. They agree here — but check that assumption in production.
4. **Array columns.** `BPCUSTOMER.REP_0` / `REP_1` (~18% have a second rep),
   `ITMMASTER.TSICOD_0..2`. These need unpivoting, and `REP_1` will silently
   double-count commission if you don't decide on ownership.
5. **Local menus.** `ORDSTA_0`, `ITMSTA_0`, `TRSTYP_0`, `REOMODE_0` are integers.
   Labels are in `APLSTD`; French translations in `ATEXTRA`.
6. **HubSpot strings.** `deal.amount` and `hs_deal_stage_probability` are
   varchar. Cast, and handle the nulls.
7. **HubSpot archived records.** ~4% of companies, 3% of contacts, 2% of deals.
   Connectors land these; they are not deletes.
8. **Duplicate contacts.** 40 near-duplicate contact records with mangled emails.
9. **The ERP handoff.** Of 238 closed-won deals, only 145 have
   `erp_order_number` populated, and only **96 join cleanly** — the rest are
   lowercased, prefix-stripped, or contain two order numbers in one field.
10. **Paycom exports.** All dates `MM/DD/YYYY` strings, all amounts strings,
    `employee_code` is text. `location_code` (`DAL-01`) does not match
    `FACILITY.FCY_0` (`US001`).
11. **Netstock lag and orphans.** `last_sync_at = 2026-09-02`, so it's stale
    relative to X3. 35 item-locations reference items with no `ITMMASTER` row.
12. **Pangea event ordering.** ~4% of `tracking_event` rows have timestamps
    out of sequence relative to `event_seq` — carrier-supplied data. Don't
    assume `min(event_ts)` is the pickup.
13. **Pangea charges ≠ cost.** `shipment.total_cost_usd` does not always equal
    `sum(charge.amount_usd)` — accessorials post late.
14. **CDC hooks.** X3 tables carry `UPDTICK_0`. HubSpot has
    `hs_lastmodifieddate`. Paycom exports have neither — full refresh only.
    That asymmetry should drive your ingestion pattern.

---

## 5. Starter queries

```sql
-- Revenue by site and quarter
SELECT v."SALFCY_0", date_trunc('quarter', v."INVDAT_0") AS qtr,
       sum(v."AMTNOTLIN_0") AS net_rev
FROM sage_x3."SINVOICEV" v GROUP BY 1,2 ORDER BY 1,2;

-- Forecast accuracy by ABC class (Netstock -> ERP item)
SELECT il.abc_class, count(*) AS periods,
       round(median(fa.abs_pct_error),1) AS median_mape
FROM netstock.forecast_accuracy fa
JOIN netstock.item_location il
  ON fa.item_code = il.item_code AND fa.location_code = il.location_code
WHERE fa.abs_pct_error IS NOT NULL
GROUP BY 1 ORDER BY 1;

-- Order-to-ship lead time, guarding the sentinel
SELECT o."SALFCY_0",
       round(avg(date_diff('day', o."ORDDAT_0", o."SHIDAT_0")),1) AS avg_days
FROM sage_x3."SORDER" o
WHERE o."SHIDAT_0" > DATE '1900-01-01'
GROUP BY 1;

-- How bad is the CRM-to-ERP customer match, really?
SELECT count(*) AS hs_companies,
       count(*) FILTER (WHERE c."BPCNUM_0" IS NOT NULL) AS exact_name_match
FROM hubspot.company h
LEFT JOIN sage_x3."BPCUSTOMER" c ON upper(h.name) = upper(c."BPCNAM_0");
```

---

## 6. Regenerating and rescaling

`generate_mock_sources.py` is self-contained. The `SCALE` block near the top
controls volumes (`N_ORDERS`, `N_ITEMS`, `N_CUSTOMERS`, date range). Bump
`N_ORDERS` to 400,000 if you want to test whether DuckDB alone gets the client
through the Snowflake decision.

`schema.sql` is portable DDL generated from the loaded database — drop it into
Postgres or SQL Server when you move from exploration to extraction design.
Note that DuckDB will not reproduce source-system *behavior* (concurrency,
referential integrity, CDC), so plan on a real RDBMS for that phase.
