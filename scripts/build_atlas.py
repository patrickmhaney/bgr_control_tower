"""Build the shareable diagram atlas from the diagrams committed in docs/.

    python scripts/build_atlas.py [output.html]

The Mermaid source is read out of docs/data_model.md and docs/ingestion.md
rather than copied, so the shared page cannot drift from the repository. The
captions live here because they are written for someone reading the picture
cold, without the surrounding document.

Each figure asserts on a distinctive substring of the diagram it expects, so
reordering or removing a diagram in the docs fails the build instead of
silently shifting every caption by one.
"""
from __future__ import annotations

import html
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FENCE = re.compile(r"```mermaid\n(.*?)```", re.S)


def blocks(filename: str) -> list[str]:
    with open(os.path.join(ROOT, "docs", filename)) as fh:
        return [m.group(1).rstrip() for m in FENCE.finditer(fh.read())]


# (source file, index, expected substring, title, caption, note)
FIGURES = [
    ("§1", "Getting the data out",
     "Five systems, five different problems. The extraction layer is real code; "
     "only the five clients that talk to the source systems are stood in for. "
     "Everything here was measured by building it, not by reasoning about it.",
     [
      ("ingestion.md", 0, "ingestion/simulators/",
       "The seam",
       "Five files stand between the pipeline and five real source systems. They are the only files that change to go live.",
       "Everything below the seam is written against rows. A row from a real ERP looks exactly like a row from this one, which is why the 46 extraction specs, the watermark logic and all 80 dbt models are already production code."),

      ("ingestion.md", 1, "project_landing_to_raw",
       "Two stages, not one",
       "Extraction lands an append-only Parquet archive; a pure-SQL projection builds the raw schemas from it.",
       "Loading straight into the warehouse would have been half the code. The second stage buys replay — rebuild without touching a source, which matters most for Paycom, where an export is gone once the next one overwrites it."),

      ("ingestion.md", 2, "NOT a watermark",
       "How the ERP gets read, and what it loses",
       "19 of 22 Sage X3 tables carry no modification date, so line tables are windowed through their parent's business date.",
       "UPDTICK_0 looks like a change signal and is not: it is a per-row lock counter, not a sequence. The trap is on the right — a line amended today on an order raised two years ago falls outside any window keyed on the order date."),

      ("ingestion.md", 3, "incremental would be WRONG",
       "What can be read incrementally",
       "A second run reads 46% of the rows. Two of the five sources read everything, every time.",
       "Paycom has no change signal of any kind and never will. Netstock is different: it regenerates wholesale, so an incremental read would be actively wrong — a row that drops out of the recomputed set would persist in the warehouse forever."),

      ("ingestion.md", 4, "sequenceDiagram",
       "How 26 rows disappeared",
       "Offset pagination over a non-unique sort key lost 26 rows and duplicated 26 others — and the row count never changed.",
       "This one actually happened during the build. A count-based reconciliation passed. The only thing that caught it was a grain uniqueness test in dbt, which is the argument for keeping those tests on every staging model."),
     ]),

    ("§2", "The five source systems",
     "Cardinalities and row counts are measured, not read off the schema. The "
     "annotations on the columns are the landmines: what is CHAR-padded, which "
     "dates are sentinels, which enums need a lookup, which key is not a key.",
     [
      ("data_model.md", 0, "SORDERQ ||--o| SINVOICED",
       "Sage X3 — ERP",
       "Every relationship resolves 100% after trimming. The risk in this estate is entirely at the system boundaries.",
       "Two things to notice: SORDERQ and SORDERP split one logical order line across two physical tables, and STOJOU reconciles on the sales side but not the purchase side — all 10,421 shipment movements reach an order, none of the 4,217 receipts reach a purchase order."),

      ("data_model.md", 1, "the only link to X3",
       "HubSpot — CRM",
       "A connector landing: string properties, associations as a separate many-to-many, archived instead of deletes.",
       "company.name is the only candidate join to the ERP, and hubspot.owner.email is an exact match to Paycom's work_email — the best identity key in the estate, and not in the documented join map."),

      ("data_model.md", 2, "150 rows for 138 people",
       "Paycom — payroll",
       "Flat report exports. Every date a string, every amount a string, and no change-tracking column anywhere.",
       "employee_code is a primary key that does not identify a person: 12 emails appear twice with the same legal name and two different codes. gl_mapping is drawn as a solid line in the documented join map and is not one — none of its GL accounts exist in the ledger."),

      ("data_model.md", 3, "35 orphaned from X3",
       "Netstock — demand planning",
       "Regenerated wholesale on each sync, with one last_sync_at across every row.",
       "replenishment_recommendation.erp_po_number is a clean cross-system link the documented join map does not mention: sparse at 247 of 896 rows, but 100% accurate where present. It is the only reliable path from planning back to procurement."),

      ("data_model.md", 4, "out of order vs event_seq",
       "Pangea — freight visibility",
       "Product still unidentified, but the data is internally consistent with a freight platform.",
       "Two structural facts drive everything built on top: the header cost and the charge lines never agree, and event timestamps are not monotonic in event_seq — so milestones are extracted by event code, never by earliest timestamp."),
     ]),

    ("§3", "Where the systems meet",
     "The part that matters for the design. Solid arrows are keys that resolve. "
     "Dashed arrows are the seams, and each one carries its measured cost.",
     [
      ("data_model.md", 5, "NOT in the join map",
       "The cross-system join map",
       "Three of the seven cross-system links are not in the documented join map, and two of those are the best keys available.",
       "The dashed lines are where the sprint goes. Tiered matching takes HubSpot-to-ERP customer coverage from 65.8% to 88.1%; repairing case, prefix and multi-value references takes the CRM-to-ERP handoff from 96 deals to 145."),
     ]),

    ("§4", "The model the dashboards read",
     "One conformed core, process-agnostic. Five dimensions, four atomic facts, "
     "and every fact-to-dimension relationship asserted by a test rather than "
     "assumed by the BI tool.",
     [
      ("data_model.md", 6, "source_scope",
       "The dimensional model",
       "Five conformed dimensions and four atomic facts. Nine presentation views sit on top; none of them contain business logic.",
       "dim_customer carries its own entity-resolution result: 197 matched across both systems, 23 ERP-only, 31 CRM companies with no ERP counterpart. Those 31 stay in the dimension, because dropping them would make the unmatched rate look like zero."),
     ]),

    ("§5", "How one becomes the other",
     "Extracted from the dbt manifest after a full build — this is what actually "
     "runs. 80 models across five layers, fed by 46 extraction resources.",
     [
      ("data_model.md", 7, "SQL database read",
       "The whole pipeline",
       "Source systems to exports, by layer, with what each layer is allowed to do.",
       "The two arrows leaving the semantic layer are the point of the design: one YAML definition generates both the warehouse SQL and the Power BI measures, so a dashboard and the database cannot disagree about what a metric means."),

      ("data_model.md", 8, "int_shipment_milestone",
       "Shipment path",
       "The deepest chain in the project, carrying both computable metrics.",
       "fct_shipment feeds four metrics across two different dashboards. That is the conformed core doing its job — one shipment fact, not an I2D shipment fact and an O2C shipment fact."),

      ("data_model.md", 9, "int_fx_rate",
       "Order-to-cash path",
       "X3's split line tables rejoined, and both money facts converted through one rate model.",
       "int_fx_rate feeding both facts is what stops USD and CAD being added together by accident. Every monetary column exists twice, suffixed _doc and _usd."),

      ("data_model.md", 10, "no consumer yet",
       "Entity resolution",
       "Two crosswalks, one reference repair — and two models with nothing downstream of them.",
       "int_employee_xref and int_deal_erp_order_number are built, tested and unconsumed. Their findings are governance results in their own right, and the resolution is ready for the first metric that needs it. The DAG shows the dead ends rather than hiding them."),

      ("data_model.md", 11, "the agent contract",
       "Metric and dashboard generation",
       "The part with no dbt lineage, because the edges are scripts rather than model references.",
       "The registry is compiled into a seed so dbt can enforce referential integrity between the dashboard map and the metric definitions. A typo fails the build instead of producing an empty tile."),
     ]),
]

FACTS = [
    ("5", "source systems"),
    ("233,150", "rows ingested"),
    ("46", "extraction resources"),
    ("80", "dbt models"),
    ("207", "tests, 4 warnings"),
    ("7", "metrics live, 3 blocked"),
]


def esc(text: str) -> str:
    """Mermaid source must survive HTML parsing to reach textContent intact."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "atlas.html")
    cache = {"data_model.md": blocks("data_model.md"), "ingestion.md": blocks("ingestion.md")}

    sections_html, nav_html = [], []
    figure_number = 0
    for section_index, (mark, heading, intro, figures) in enumerate(FIGURES, start=1):
        nav_html.append(
            f'<a href="#s{section_index}"><span class="nav-mark">{mark}</span>{html.escape(heading)}</a>'
        )
        items = []
        for filename, index, expected, title, caption, note in figures:
            source = cache[filename][index]
            if expected not in source:
                raise SystemExit(
                    f"docs/{filename} block {index} no longer contains {expected!r}. "
                    f"The diagrams moved; update FIGURES in scripts/build_atlas.py."
                )
            figure_number += 1
            items.append(f"""
        <figure class="fig" id="fig{figure_number}">
          <figcaption>
            <span class="fig-no">Fig {section_index}.{len(items) + 1}</span>
            <h3>{html.escape(title)}</h3>
            <p class="claim">{html.escape(caption)}</p>
          </figcaption>
          <div class="canvas"><pre class="mermaid">{esc(source)}</pre></div>
          <p class="note"><span class="note-label">What to look at</span>{html.escape(note)}</p>
        </figure>""")
        sections_html.append(f"""
      <section id="s{section_index}" class="section">
        <header class="section-head">
          <span class="section-mark">{mark}</span>
          <h2>{html.escape(heading)}</h2>
          <p class="lede">{html.escape(intro)}</p>
        </header>
        {''.join(items)}
      </section>""")

    facts = "".join(
        f'<div class="fact"><span class="fact-n">{n}</span>'
        f'<span class="fact-l">{html.escape(label)}</span></div>'
        for n, label in FACTS
    )

    with open(os.path.join(ROOT, "scripts", "atlas_template.html")) as fh:
        template = fh.read()

    page = (template
            .replace("<!--NAV-->", "\n        ".join(nav_html))
            .replace("<!--FACTS-->", facts)
            .replace("<!--SECTIONS-->", "\n".join(sections_html))
            .replace("<!--COUNT-->", str(figure_number)))

    with open(out_path, "w") as fh:
        fh.write(page)
    print(f"{figure_number} figures -> {os.path.relpath(out_path, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
