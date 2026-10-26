# The synthetic sources

`sources/` simulates the three source systems, a cloud cost export, and the
answer key MDM is scored against. Everything runs on this data - laptop, CI
and Azure dev - so the platform is always testable end to end.

## Fidelity

| System | Fidelity | Shape |
|---|---|---|
| Sage X3 | High | Real X3 naming: `_0` suffixes, array columns (`REP_0`/`REP_1`), `UPDTICK_0` lock counters, CHAR padding, 1753 sentinel dates, integer local menus, no enforced keys. Read as a SQL Server database with CDC. **Verify table names against the client's folder** - `SDELIVERY`, `AUTILIS`, `STOCOUNT`, `SRETURN`, `PRECEIPT` and `PINVOICE` follow X3 conventions but are unconfirmed. |
| HubSpot | High | Shaped like the REST API: string properties, `archived` flags, associations as a separate many-to-many, owners with teams. |
| Netstock | Inferred | Grain and semantics are right (item × location, monthly forecasts, ABC/XYZ). Column names are constructed. Regenerated wholesale on each sync, two days behind the ERP. |
| Azure cost | Synthetic | A daily FOCUS export, one row per resource per day, tagged by component. |

## The clock

`generate.py` builds one deterministic timeline from 2024-07-01 to 2026-10-31.
`state_as_of(day)` removes every document dated after the day and rolls back
every later update, consistently across documents. `clock.py` writes that
state into `.data/mock_sources.duckdb`, and `advance` diffs consecutive days
into SQL Server-shaped change tables (`cdc.dbo_<TABLE>_CT`: operation 1 delete,
2 insert, 3/4 update before/after, ordered by `__$start_lsn`, `__$seqval`),
purged after a 3-day retention window. Each day carries new orders, shipments,
proof-of-delivery dates, invoices being paid, late returns, PO receipts,
supplier invoices, count sessions being posted, stock drift, HubSpot stage
moves and archivals, and the occasional hard delete.

## Landmines

Real behaviour from each system, kept on purpose:

1. **CHAR padding in X3.** `SORDERQ.ITMREF_0`, `SORDERP.ITMREF_0`, `STOJOU.ITMREF_0`,
   `SORDER.BPCORD_0` are space-padded; the masters are not. A naive join returns
   zero rows. Staging trims.
2. **Sentinel dates.** `1753-01-01` means "no date". Any date difference that
   does not null it produces a ~99,000-day average.
3. **Split line tables.** Quantity in `SORDERQ`, price in `SORDERP`; both carry
   `ITMREF_0`. `int_sales_order_line` asserts they agree.
4. **Array columns.** `BPCUSTOMER.REP_1` (~18% of customers) and `ITMMASTER.TSICOD_0..2`.
5. **Local menus.** `ORDSTA_0`, `ITMSTA_0`, `TRSTYP_0` are integers; labels in `APLSTD`.
6. **Rep reassignments.** A customer's `REP_0` changes on its last update date.
   CDC keeps the before-image, which is the as-was history (open question 11).
7. **Hard deletes.** A quarter of cancelled orders are deleted outright two weeks
   later. Only CDC sees it.
8. **Updates in place.** `SINVOICEV.PAYDAT_0`, `PORDERQ.RCPQTY_0`, `SORDERQ.SHTQTY_0`
   and `SDELIVERY.DLVDAT_0` change long after the document's own date - the
   updates a business-date window misses.
9. **Partial deliveries.** 6% of shipped orders go out in two deliveries, and the
   second one is usually late.
10. **HubSpot strings.** `deal.amount` and `hs_deal_stage_probability` are varchar.
11. **HubSpot archived records and hard deletes.** ~4% of companies are archived
    (flagged, not deleted); ~1% of contacts are deleted outright (a privacy
    request), which only a key reconciliation notices.
12. **Duplicate contacts.** 40 near-duplicates with mangled emails.
13. **The ERP handoff.** `deal.erp_order_number` is missing on ~40% of won deals and
    malformed on many of the rest (lower-cased, prefix-stripped, two numbers).
14. **Customer names drift.** No shared key between HubSpot and X3; ~22% of
    names gain punctuation, ~10% lose their suffix, ~6% are upper-cased.
15. **Employee identity.** Two X3 users have no email; one HubSpot owner's email
    arrives in different casing. EDI, WMS and ADMIN are system users.
16. **Unresolvable return references.** ~8% of returns carry a blank or
    lower-cased order number. They are kept, not dropped.
17. **Uncredited returns.** 14% of returns have no credit memo yet, so recent
    months' return rates rise as credits post.
18. **`PORDERQ.RCPDAT_0` is the last receipt only.** A partial delivery has two
    receipt lines and one PO-line date; matching on the PO line would treat
    every partial delivery as a variance.
19. **Count sessions are not recoverable.** `STOCOUNTD.QTYTHEO_0` is the system
    quantity at count time; it cannot be rebuilt from `STOCK` later.
20. **Netstock lag and orphans.** Two days behind X3; 35 item-locations reference
    items the ERP does not have.

## The answer key

`truth.customer_identity`, `truth.employee_identity` and
`truth.employee_department` record who each source record really is. Only
`mdm/run.py` reads them, to score providers. Nothing in the pipeline does.

## Changing the data

Edit `sources/generate.py` and run `make mock run`. The timeline cache
(`.data/timeline.pkl`) rebuilds itself when the generator changes. A change to
the data changes numbers: re-freeze the golden answers and explain the diff.
