"""The extraction spec: one entry per source table, and how it must be read.

This module is the scope document for ingestion. Everything the extraction
design has to decide - can this table be read incrementally, on what column,
with what key, and what breaks if you get it wrong - is stated here rather than
buried in the extractor.

Read `docs/ingestion.md` alongside it for the per-system access patterns, the
credentials each one needs, and where the calendar time actually goes.

Extraction strategies
---------------------
FULL_REFRESH   Read the whole table every run. The right default at this data
               volume, and the only option for a table with no change signal.
HEADER_WINDOW  The table has no date of its own, so it is windowed through its
               parent's business date. Upserted on the primary key.
MODIFIED_DATE  The table carries a modification date. Windowed on it, with a
               lookback, and upserted.
API_CURSOR     REST API with a server-side "modified since" filter.
SNAPSHOT       The source regenerates the whole dataset each sync. Replace.
FILE_DROP      Scheduled report export. Whatever the file contains is the truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Strategy(str, Enum):
    FULL_REFRESH = "full_refresh"
    HEADER_WINDOW = "header_window"
    MODIFIED_DATE = "modified_date"
    API_CURSOR = "api_cursor"
    SNAPSHOT = "snapshot"
    FILE_DROP = "file_drop"


#: How far back a windowed extract reaches beyond its high-water mark.
#: Covers backdated entries, late corrections and clock skew between the
#: source and the extractor. 90 days is deliberately generous - the cost is
#: re-reading rows you already have, and the cost of getting it wrong is
#: silently missing a backdated invoice forever.
DEFAULT_LOOKBACK_DAYS = 90


@dataclass(frozen=True)
class TableSpec:
    name: str
    strategy: Strategy
    primary_key: tuple[str, ...] = ()
    #: Column carrying the change signal, for MODIFIED_DATE / API_CURSOR.
    cursor_column: str | None = None
    #: (parent_table, join_column, parent_date_column) for HEADER_WINDOW.
    window_via: tuple[str, str, str] | None = None
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    #: How a hard delete in the source is detected. Merge disposition never
    #: removes a row, so a row deleted upstream persists in the warehouse
    #: forever unless something reconciles the key set. Declaring the intent
    #: here rather than in prose keeps the decision next to the strategy and
    #: the lookback, where whoever builds it will find it.
    #:   never   full refresh already replaces the whole table, or deletes do
    #:           not happen on this object
    #:   weekly  needs a periodic key reconciliation against the source
    reconcile_keys: str = "never"
    #: Why this strategy, and what to watch for. Shown by `--explain`.
    note: str = ""

    @property
    def write_disposition(self) -> str:
        if self.strategy in (Strategy.FULL_REFRESH, Strategy.SNAPSHOT, Strategy.FILE_DROP):
            return "replace"
        return "merge"


@dataclass(frozen=True)
class SourceSpec:
    name: str
    system: str
    access: str
    auth: str
    change_tracking: str
    tables: tuple[TableSpec, ...]
    #: Known pitfalls that bite during extraction specifically, not modelling.
    pitfalls: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Sage X3 - read from the ERP database
# ---------------------------------------------------------------------------
# Measured against the extract: 19 of 22 tables carry NO modification date, and
# the three that do carry a DATE, not a timestamp - so even the good case is
# day-grain. UPDTICK_0 is present on 14 tables and is NOT a watermark: it is a
# per-row optimistic-lock counter, not a table-wide monotonic sequence, so
# `WHERE UPDTICK_0 > :last` is meaningless. Use it to detect whether a specific
# row changed during reconciliation, never to drive an extract.
#
# The line tables therefore go through their header's business date.

SAGE_X3 = SourceSpec(
    name="sage_x3",
    system="Sage X3 (ERP)",
    access="Direct read against the X3 database (SQL Server or Oracle), ideally a read replica.",
    auth="Database login with SELECT on the production folder schema.",
    change_tracking=(
        "Weak. UPDTICK_0 is a per-row lock counter, not a sequence. Three tables "
        "carry UPDDAT_0 as a DATE. Everything else needs a business-date window "
        "or a full refresh. Database-level Change Tracking or CDC is the robust "
        "answer and is an infrastructure request, not a data-engineering one."
    ),
    pitfalls=(
        "A real X3 folder holds 2,000-4,000 tables. The 22 below are the ones "
        "that matter for the current metric set - that selection is the single "
        "biggest piece of discovery work this POC already did.",
        "X3 installs have multiple folders (SEED plus a production folder). "
        "Confirm which schema is production before pointing anything at it.",
        "Sage's supported position is read-only access. Never write, and use a "
        "replica so reporting queries cannot contend with transaction posting.",
        "CHAR padding is applied on the source side, so it arrives in the "
        "extract. It is stripped in staging, not here - landing stays lossless.",
    ),
    tables=(
        # --- reference data: small, static, always full ---
        TableSpec("COMPANY", Strategy.FULL_REFRESH, ("CPY_0",),
                  note="2 rows. Full refresh forever. The production extract "
                       "must also carry the company currency column (CUR_0 in "
                       "a standard folder - confirm against the install): "
                       "int_fx_rate derives a document-to-company-currency "
                       "rate and publishes it as a reporting-currency rate, "
                       "which is only correct where the two agree. Without "
                       "this column that cannot be checked. See open question 10."),
        TableSpec("FACILITY", Strategy.FULL_REFRESH, ("FCY_0",),
                  note="3 rows."),
        TableSpec("APLSTD", Strategy.FULL_REFRESH, ("CHAPTER_0", "CODE_0", "LANNUM_0"),
                  note="Local menu labels. Changes only on configuration."),
        TableSpec("ATEXTRA", Strategy.FULL_REFRESH,
                  ("CODFIC_0", "ZONE_0", "LANNUM_0", "IDENT1_0", "IDENT2_0"),
                  note="Translations. In a real folder this is large - revisit."),
        TableSpec("REPRESENT", Strategy.FULL_REFRESH, ("REPNUM_0",),
                  note="28 rows."),
        TableSpec("BPADDRESS", Strategy.FULL_REFRESH, ("BPANUM_0", "BPAADD_0"),
                  note="No change signal at all - no UPDTICK_0, no dates."),
        TableSpec("BPSUPPLIER", Strategy.FULL_REFRESH, ("BPSNUM_0",),
                  note="45 rows. UPDTICK_0 present but unusable as a watermark."),
        TableSpec("BPARTNER", Strategy.FULL_REFRESH, ("BPRNUM_0",),
                  note="265 rows. No date column despite carrying UPDTICK_0."),
        TableSpec("ITMFACILIT", Strategy.FULL_REFRESH, ("ITMREF_0", "STOFCY_0"),
                  note="Item x site planning params. No date column."),
        TableSpec("STOCK", Strategy.FULL_REFRESH,
                  ("STOFCY_0", "ITMREF_0", "LOT_0", "LOC_0"),
                  note="Current on-hand only, no history. Full refresh is the "
                       "only correct read - a windowed one would strand rows "
                       "that went to zero."),

        # --- masters that DO carry a modification date ---
        TableSpec("ITMMASTER", Strategy.MODIFIED_DATE, ("ITMREF_0",),
                  cursor_column="UPDDAT_0",
                  note="UPDDAT_0 is a DATE, so the window is day-grain: a row "
                       "changed twice today is caught once. Fine for a master.",
                  reconcile_keys="weekly"),
        TableSpec("BPCUSTOMER", Strategy.MODIFIED_DATE, ("BPCNUM_0",),
                  cursor_column="UPDDAT_0",
                  note="Same day-grain caveat.",
                  reconcile_keys="weekly"),

        # --- transaction headers: windowed on their own business date ---
        TableSpec("SORDER", Strategy.MODIFIED_DATE, ("SOHNUM_0",),
                  cursor_column="UPDDAT_0",
                  note="The only transaction header with a modification date.",
                  reconcile_keys="weekly"),
        TableSpec("SINVOICEV", Strategy.HEADER_WINDOW, ("NUM_0",),
                  window_via=("SINVOICEV", "NUM_0", "INVDAT_0"),
                  note="No modification date. Windowed on its own INVDAT_0, "
                       "which is a BUSINESS date - so a payment recorded "
                       "against an old invoice is missed unless the lookback "
                       "covers it. This is why the lookback is 90 days and why "
                       "PAYDAT_0 changes are the thing to watch.",
                  reconcile_keys="weekly"),
        TableSpec("PORDER", Strategy.HEADER_WINDOW, ("POHNUM_0",),
                  window_via=("PORDER", "POHNUM_0", "ORDDAT_0"),
                  note="Same pattern. Late receipts update old POs - lookback matters.",
                  reconcile_keys="weekly"),
        TableSpec("GACCENTRY", Strategy.HEADER_WINDOW, ("NUM_0",),
                  window_via=("GACCENTRY", "NUM_0", "ACCDAT_0"),
                  note="Posted entries are immutable in practice, so a window "
                       "on ACCDAT_0 is safe. Confirm the client does not "
                       "reverse-and-repost into prior periods.",
                  reconcile_keys="weekly"),
        TableSpec("STOJOU", Strategy.HEADER_WINDOW, ("ROWID",),
                  window_via=("STOJOU", "ROWID", "IPTDAT_0"),
                  note="Append-only movement journal. ROWID is monotonic, so "
                       "this could be a cursor on ROWID instead - cheaper and "
                       "exact. Left on the date window for consistency; switch "
                       "it if volume becomes a problem.",
                  reconcile_keys="weekly"),

        # --- line tables: no date of their own, windowed through the header ---
        TableSpec("SORDERQ", Strategy.HEADER_WINDOW, ("SOHNUM_0", "SOPLIN_0"),
                  window_via=("SORDER", "SOHNUM_0", "ORDDAT_0"),
                  note="No date column. Reached through SORDER.ORDDAT_0. A line "
                       "amended on an old order is missed unless the lookback "
                       "covers the ORDER date, not the amendment date - the "
                       "single most likely silent data-loss bug in this design.",
                  reconcile_keys="weekly"),
        TableSpec("SORDERP", Strategy.HEADER_WINDOW, ("SOHNUM_0", "SOPLIN_0"),
                  window_via=("SORDER", "SOHNUM_0", "ORDDAT_0"),
                  note="Same as SORDERQ. Both must use the same window or the "
                       "two halves of a line will disagree.",
                  reconcile_keys="weekly"),
        TableSpec("SINVOICED", Strategy.HEADER_WINDOW, ("NUM_0", "SIDLIN_0"),
                  window_via=("SINVOICEV", "NUM_0", "INVDAT_0"),
                  note="No UPDTICK_0 and no dates. Header window is the only option.",
                  reconcile_keys="weekly"),
        TableSpec("PORDERQ", Strategy.HEADER_WINDOW, ("POHNUM_0", "POPLIN_0"),
                  window_via=("PORDER", "POHNUM_0", "ORDDAT_0"),
                  note="RCPQTY_0/RCPDAT_0 are updated in place when goods "
                       "arrive, so a PO ordered outside the window and received "
                       "inside it is MISSED. Strong argument for full refresh "
                       "on this table, or for database CDC.",
                  reconcile_keys="weekly"),
        TableSpec("GACCENTRYD", Strategy.HEADER_WINDOW, ("NUM_0", "LIN_0"),
                  window_via=("GACCENTRY", "NUM_0", "ACCDAT_0"),
                  note="No UPDTICK_0, no dates of its own.",
                  reconcile_keys="weekly"),

        # --- returns: the Return Rate source ---
        TableSpec("SRETURN", Strategy.HEADER_WINDOW, ("SRHNUM_0",),
                  window_via=("SRETURN", "SRHNUM_0", "RTNDAT_0"),
                  note="Customer returns. RTNDAT_0 is a business date and a "
                       "return can be raised months after the order, so the "
                       "window must be on the RETURN date - windowing on the "
                       "order date would miss every late return, which is most "
                       "of them.",
                  reconcile_keys="weekly"),
        TableSpec("SRETURND", Strategy.HEADER_WINDOW, ("SRHNUM_0", "SRDLIN_0"),
                  window_via=("SRETURN", "SRHNUM_0", "RTNDAT_0"),
                  note="No date of its own. Reached through the return header.",
                  reconcile_keys="weekly"),

        # --- purchasing: the Match Rate sources ---
        TableSpec("PRECEIPT", Strategy.HEADER_WINDOW, ("PTHNUM_0",),
                  window_via=("PRECEIPT", "PTHNUM_0", "RCPDAT_0"),
                  note="Goods receipts. Unlike PORDERQ.RCPDAT_0 this is a "
                       "document with its own date, so a receipt against an "
                       "old PO lands inside the window on its own merit. This "
                       "is the table that makes PORDERQ's update-in-place "
                       "problem survivable.",
                  reconcile_keys="weekly"),
        TableSpec("PRECEIPTD", Strategy.HEADER_WINDOW, ("PTHNUM_0", "PTDLIN_0"),
                  window_via=("PRECEIPT", "PTHNUM_0", "RCPDAT_0"),
                  note="Carries the PO line reference, which is what makes a "
                       "partial or multi-delivery receipt matchable.",
                  reconcile_keys="weekly"),
        TableSpec("PINVOICE", Strategy.HEADER_WINDOW, ("NUM_0",),
                  window_via=("PINVOICE", "NUM_0", "INVDAT_0"),
                  note="Supplier invoices. Same business-date caveat as "
                       "SINVOICEV: an invoice approved or repriced after "
                       "posting changes in place without moving INVDAT_0. "
                       "Watch INVSTA_0 and keep the lookback wide.",
                  reconcile_keys="weekly"),
        TableSpec("PINVOICED", Strategy.HEADER_WINDOW, ("NUM_0", "PIDLIN_0"),
                  window_via=("PINVOICE", "NUM_0", "INVDAT_0"),
                  note="Holds the PO and receipt references. A null PTHNUM_0 "
                       "is meaningful - it is an invoice with no receipt - so "
                       "do not filter it in the extractor.",
                  reconcile_keys="weekly"),

        # --- counting: the Inventory Accuracy source ---
        TableSpec("STOCOUNT", Strategy.HEADER_WINDOW, ("SESNUM_0",),
                  window_via=("STOCOUNT", "SESNUM_0", "CNTDAT_0"),
                  note="Count sessions. VERIFY THE TABLE NAME against the "
                       "client's folder - the counting mechanism is right, the "
                       "name is constructed. A session stays open while it is "
                       "being counted, so the lookback must cover the longest "
                       "count cycle or sessions will land half-posted.",
                  reconcile_keys="weekly"),
        TableSpec("STOCOUNTD", Strategy.HEADER_WINDOW, ("SESNUM_0", "CNTLIN_0"),
                  window_via=("STOCOUNT", "SESNUM_0", "CNTDAT_0"),
                  note="One row per counted position. QTYTHEO_0 is the system "
                       "quantity AT COUNT TIME and is not recoverable later "
                       "from STOCK - if this table is not captured, inventory "
                       "accuracy cannot be rebuilt retrospectively.",
                  reconcile_keys="weekly"),
    ),
)


# ---------------------------------------------------------------------------
# HubSpot - REST API
# ---------------------------------------------------------------------------
HUBSPOT = SourceSpec(
    name="hubspot",
    system="HubSpot (CRM)",
    access="REST API v3/v4 over HTTPS. No network work required.",
    auth="Private app token with the relevant object scopes.",
    change_tracking=(
        "Good. hs_lastmodifieddate on every object supports a genuine "
        "modified-since cursor."
    ),
    pitfalls=(
        "Archived records are NOT returned by default. You must request them "
        "explicitly. Miss it and you silently lose 12 companies, 23 contacts "
        "and 11 deals here - and archived is not the same as deleted, so the "
        "mart must decide, not the extractor.",
        "Rate limits are per-token and per-app. Extract must back off rather "
        "than fail, and a full historical backfill needs pacing.",
        "Custom properties are not returned unless named. Enumerate the "
        "property schema first and re-check it on every run - a new property "
        "appears silently and a renamed one disappears silently.",
        "Associations moved to a separate v4 API. The denormalised *_id columns "
        "on deal and contact are convenience copies and can lag.",
    ),
    tables=(
        TableSpec("company", Strategy.API_CURSOR, ("id",), cursor_column="hs_lastmodifieddate",
                  note="Request archived=true as a second pass.",
                  reconcile_keys="weekly"),
        TableSpec("contact", Strategy.API_CURSOR, ("id",), cursor_column="lastmodifieddate",
                  note="Note the property name differs from company - it is "
                       "lastmodifieddate here, not hs_lastmodifieddate.",
                  reconcile_keys="weekly"),
        TableSpec("deal", Strategy.API_CURSOR, ("id",), cursor_column="hs_lastmodifieddate",
                  reconcile_keys="weekly"),
        TableSpec("deal_stage_history", Strategy.FULL_REFRESH, ("deal_id", "stage", "changed_at"),
                  note="Derived from the deal property history endpoint. No "
                       "cursor of its own; refresh with its parent deal."),
        TableSpec("association", Strategy.FULL_REFRESH, ("from_id", "to_id", "association_type"),
                  note="v4 batch-read API. No modified-since filter, so it is a "
                       "full crawl. At real volume this is the slowest resource."),
        TableSpec("engagement", Strategy.API_CURSOR, ("id",), cursor_column="created_at",
                  reconcile_keys="weekly"),
        TableSpec("owner", Strategy.FULL_REFRESH, ("id",), note="22 rows."),
        TableSpec("pipeline_stage", Strategy.FULL_REFRESH, ("pipeline_id", "stage_id"),
                  note="Configuration, not data."),
    ),
)


# ---------------------------------------------------------------------------
# Paycom - scheduled report exports
# ---------------------------------------------------------------------------
PAYCOM = SourceSpec(
    name="paycom",
    system="Paycom (payroll)",
    access=(
        "Scheduled Report Center exports delivered to SFTP. There is no "
        "queryable backend and the API is too thin to drive reporting."
    ),
    auth="SFTP credentials plus a Paycom admin who can configure the reports.",
    change_tracking="None. Full refresh only, forever.",
    pitfalls=(
        "This is the long pole on calendar time and it is not technical. "
        "Configuring scheduled reports and enabling SFTP delivery needs a "
        "Paycom admin and often Paycom support. Start it in week one; the "
        "clock runs independently of your build.",
        "A report that silently stops arriving looks exactly like a report with "
        "no changes. File freshness must be asserted, not assumed - the "
        "extractor fails if the newest file is older than the expected cadence.",
        "Everything is a string, including dates as MM/DD/YYYY and all amounts. "
        "Landing keeps them as strings; staging casts. Do not cast in the "
        "extractor or you lose the ability to see what actually arrived.",
        "Payroll is PII - this extract carries salaries and SSN fragments. "
        "Expect a security review, restrict the raw schema, and budget calendar "
        "time for both.",
        "Column order and headers change when someone edits the saved report. "
        "Read by header name, never by position, and alert on unexpected columns.",
    ),
    tables=(
        TableSpec("employee", Strategy.FILE_DROP, ("employee_code",)),
        TableSpec("check", Strategy.FILE_DROP, ("check_id",)),
        TableSpec("earning_detail", Strategy.FILE_DROP, ("check_id", "earning_code")),
        TableSpec("deduction_detail", Strategy.FILE_DROP, ("check_id", "deduction_code")),
        TableSpec("tax_detail", Strategy.FILE_DROP, ("check_id", "tax_code")),
        TableSpec("gl_mapping", Strategy.FILE_DROP, ("code_type", "code")),
    ),
)


# ---------------------------------------------------------------------------
# Netstock - snapshot API
# ---------------------------------------------------------------------------
NETSTOCK = SourceSpec(
    name="netstock",
    system="Netstock (demand planning)",
    access="REST API, unconfirmed. Vendor discovery required - see open question.",
    auth="Unknown. Assume API key.",
    change_tracking=(
        "None needed. The dataset is regenerated wholesale on each sync and "
        "carries a single last_sync_at, so a snapshot replace is the correct "
        "read and an incremental one would be wrong."
    ),
    pitfalls=(
        "SCHEDULE RISK. Netstock's API is built to sync with an ERP, not to be "
        "a warehouse source. Get a sample extract during discovery, not during "
        "build - this is one of the two sources that could move the date.",
        "The snapshot is stale relative to the ERP by construction. Carry "
        "last_sync_at through to the mart so freshness is visible rather than "
        "assumed.",
        "35 item-locations reference items that do not exist in the ERP. Land "
        "them; do not filter in the extractor.",
    ),
    tables=(
        TableSpec("item_location", Strategy.SNAPSHOT, ("item_code", "location_code")),
        TableSpec("forecast", Strategy.SNAPSHOT, ("item_code", "location_code", "period_start")),
        TableSpec("forecast_accuracy", Strategy.SNAPSHOT,
                  ("item_code", "location_code", "period_start")),
        TableSpec("replenishment_recommendation", Strategy.SNAPSHOT, ("recommendation_id",)),
        TableSpec("supplier", Strategy.SNAPSHOT, ("supplier_code",)),
    ),
)


# ---------------------------------------------------------------------------
# Pangea - REST API
# ---------------------------------------------------------------------------
PANGEA = SourceSpec(
    name="pangea",
    system="Pangea (freight visibility) - product unconfirmed",
    access="Assumed REST API. Some freight platforms are EDI-only.",
    auth="Unknown.",
    change_tracking="Assumed created_at cursor on shipments; children fetched with the parent.",
    pitfalls=(
        "SCHEDULE RISK. The product is still unidentified. Two of the four "
        "buildable metrics sit entirely on this source, so a surprise here is "
        "expensive. Identify it before committing to a date.",
        "Child records (charges, tracking events) usually hang off the shipment "
        "endpoint. Fetching them per shipment is an N+1 that will not scale to "
        "a backfill - look for a bulk or date-ranged child endpoint first.",
        "Charges post late. A shipment fetched the day it ships will be missing "
        "accessorials that arrive weeks later, so the cursor must revisit "
        "shipments, not just collect new ones. This is why shipments use a "
        "lookback rather than a strict high-water mark.",
        "Tracking event timestamps arrive out of order relative to event_seq on "
        "1.29% of rows. That is the carrier's data - land it as sent.",
    ),
    tables=(
        TableSpec("shipment", Strategy.API_CURSOR, ("shipment_id",), cursor_column="created_at",
                  note="Lookback is essential: accessorial charges and delivery "
                       "events land after the shipment is created.",
                  reconcile_keys="weekly"),
        TableSpec("charge", Strategy.HEADER_WINDOW, ("shipment_id", "charge_code"),
                  window_via=("shipment", "shipment_id", "created_at"),
                  note="Fetched with the parent shipment.",
                  reconcile_keys="weekly"),
        TableSpec("tracking_event", Strategy.HEADER_WINDOW, ("shipment_id", "event_seq"),
                  window_via=("shipment", "shipment_id", "created_at"),
                  reconcile_keys="weekly"),
        TableSpec("shipment_leg", Strategy.HEADER_WINDOW, ("shipment_id", "leg_seq"),
                  window_via=("shipment", "shipment_id", "created_at"),
                  reconcile_keys="weekly"),
        TableSpec("carrier", Strategy.FULL_REFRESH, ("scac",), note="7 rows."),
    ),
)


SOURCES: dict[str, SourceSpec] = {
    s.name: s for s in (SAGE_X3, HUBSPOT, PAYCOM, NETSTOCK, PANGEA)
}


def table_spec(source: str, table: str) -> TableSpec:
    for spec in SOURCES[source].tables:
        if spec.name == table:
            return spec
    raise KeyError(f"{source}.{table} is not in the extraction spec")
