#!/usr/bin/env python3
"""
Mock source-system databases for data warehouse solutioning.

Generates five source schemas in a single DuckDB file:
    sage_x3   - ERP        (highest fidelity: real X3 naming conventions)
    hubspot   - CRM        (API/connector-shaped, as Fivetran/Airbyte would land it)
    paycom    - Payroll    (flat export-shaped; Paycom has no queryable backend)
    netstock  - Forecasting(inferred shape)
    pangea    - Shipments  (inferred shape - generic freight platform)

Deliberate data-quality landmines are included and documented in README.md.
Scale is controlled by the SCALE block below. Deterministic (seeded).
"""

import duckdb
import random
import math
import os
from datetime import date, timedelta

SEED = 20260905
random.seed(SEED)

# Written next to this script, so regenerating works from any checkout and any
# working directory. Override with MOCK_SOURCES_DIR to write somewhere else.
OUT_DIR = os.environ.get(
    "MOCK_SOURCES_DIR", os.path.dirname(os.path.abspath(__file__))
)
OUT_DB = os.path.join(OUT_DIR, "mock_sources.duckdb")
OUT_DDL = os.path.join(OUT_DIR, "schema.sql")

# ---------------------------------------------------------------- scale ----
N_CUSTOMERS = 220
N_ITEMS = 420
N_SUPPLIERS = 45
N_EMPLOYEES = 150
N_SALES_REPS = 28
N_ORDERS = 4200
N_HS_COMPANIES = 260
N_HS_CONTACTS = 900
N_HS_DEALS = 850

START = date(2024, 7, 1)
END = date(2026, 8, 31)
TODAY = date(2026, 9, 5)

NULL_DATE = date(1753, 1, 1)  # X3-on-SQL-Server sentinel for "no date"


def rdate(a=START, b=END):
    return a + timedelta(days=random.randint(0, (b - a).days))


def pad(s, n):
    """Mimic CHAR(n) padding that X3 returns from SQL Server."""
    return str(s).ljust(n)


def money(x):
    return round(float(x), 2)


def choice_w(items, weights):
    return random.choices(items, weights=weights, k=1)[0]


# ------------------------------------------------------- shared spine ----
COMPANIES = [
    ("GLBUS", "Globex Distribution Inc", "US", "USA"),
    ("GLBCA", "Globex Distribution Canada ULC", "CA", "CAN"),
]

SITES = [
    # FCY_0, name, company, short, country, city, state
    ("US001", "Dallas TX Distribution Center", "GLBUS", "DALLAS", "USA", "Dallas", "TX"),
    ("US002", "Reno NV Distribution Center", "GLBUS", "RENO", "USA", "Reno", "NV"),
    ("CA001", "Toronto ON Distribution Center", "GLBCA", "TORONTO", "CAN", "Toronto", "ON"),
]
SITE_CODES = [s[0] for s in SITES]

# Paycom uses its own location codes -- deliberately NOT equal to FCY_0.
PAYCOM_LOC = {"US001": "DAL-01", "US002": "RNO-01", "CA001": "TOR-01"}

ITEM_CATS = ["FG", "RM", "CMP", "PKG"]
CAT_WEIGHTS = [0.45, 0.25, 0.22, 0.08]

PROD_NOUNS = ["Valve", "Bearing", "Coupling", "Gasket", "Flange", "Actuator", "Bracket",
              "Manifold", "Seal Kit", "Impeller", "Housing", "Spindle", "Bushing",
              "Regulator", "Filter Element", "Drive Shaft", "Pump Head", "Sensor Mount"]
PROD_ADJ = ["Stainless", "Carbon Steel", "Brass", "Aluminum", "Composite", "Hardened",
            "Zinc-Plated", "Nitrile", "PTFE-Lined", "Cast Iron"]
PROD_SIZE = ['1/4"', '1/2"', '3/4"', '1"', '1-1/2"', '2"', '3"', '4"', "6mm", "12mm", "25mm"]

CUST_A = ["Northwind", "Vertex", "Ironclad", "Bluepeak", "Summit", "Cardinal", "Longview",
          "Redstone", "Halcyon", "Kestrel", "Meridian", "Ashford", "Brightwater", "Copperline",
          "Dovetail", "Eastgate", "Fairmount", "Granite", "Harborview", "Ivyridge", "Juniper",
          "Keystone", "Lakeshore", "Millbrook", "Northgate", "Oakhurst", "Pinehurst", "Quarry",
          "Riverbend", "Stonebridge", "Thornton", "Union", "Vanguard", "Westfield", "Yorkville"]
CUST_B = ["Industrial", "Manufacturing", "Supply", "Fluid Systems", "Engineering", "Machine Works",
          "Process Equipment", "Hydraulics", "Fabrication", "Controls", "Components", "Technologies"]
CUST_C = ["LLC", "Inc", "Corp", "Group", "Co", "Ltd"]

FIRST = ["James", "Maria", "Robert", "Priya", "Michael", "Linda", "David", "Aisha", "John", "Sofia",
         "Daniel", "Emily", "Carlos", "Hannah", "Kevin", "Rachel", "Brian", "Nina", "Thomas", "Grace",
         "Andrew", "Chloe", "Marcus", "Elena", "Steven", "Fatima", "Paul", "Olivia", "Eric", "Naomi",
         "Victor", "Diane", "Samuel", "Leah", "Peter", "Jasmine", "Alan", "Ruth", "Tyler", "Monica"]
LAST = ["Alvarez", "Bennett", "Chowdhury", "Delgado", "Ellison", "Fontaine", "Garrison", "Huang",
        "Ibrahim", "Jankowski", "Kaminski", "Laurent", "Mbeki", "Novak", "Okafor", "Petrov",
        "Quintero", "Rasmussen", "Sandoval", "Takahashi", "Ueda", "Vasquez", "Whitfield", "Xu",
        "Yamamoto", "Zielinski", "Brennan", "Castellano", "Dubois", "Emerson", "Farrow", "Gallagher"]

US_CITIES = [("Dallas", "TX", "75201"), ("Houston", "TX", "77002"), ("Phoenix", "AZ", "85004"),
             ("Denver", "CO", "80202"), ("Chicago", "IL", "60601"), ("Atlanta", "GA", "30303"),
             ("Columbus", "OH", "43215"), ("Charlotte", "NC", "28202"), ("Seattle", "WA", "98104"),
             ("Reno", "NV", "89501"), ("Kansas City", "MO", "64106"), ("Nashville", "TN", "37201"),
             ("Portland", "OR", "97204"), ("Tampa", "FL", "33602"), ("Salt Lake City", "UT", "84101")]
CA_CITIES = [("Toronto", "ON", "M5H 2N2"), ("Mississauga", "ON", "L5B 3C2"),
             ("Calgary", "AB", "T2P 1J9"), ("Montreal", "QC", "H3B 2Y3"),
             ("Vancouver", "BC", "V6C 2T4"), ("Winnipeg", "MB", "R3C 0V8")]

# =========================================================================
#  SAGE X3
# =========================================================================
x3 = {}

x3["COMPANY"] = [
    {"CPY_0": c, "CPYNAM_0": n, "CRY_0": cry, "LEG_0": leg, "CPYLOG_0": 2 if leg == "USA" else 2}
    for c, n, cry, leg in COMPANIES
]

x3["FACILITY"] = [
    {"FCY_0": f, "FCYSHO_0": sho, "FCYNAM_0": n, "LEGCPY_0": cpy, "CRY_0": cry,
     "CTY_0": city, "SAT_0": st, "FCYSTO_0": 2, "FCYSAL_0": 2, "FCYPUR_0": 2}
    for f, n, cpy, sho, cry, city, st in SITES
]

# ------------------------------------------------------ local menus ------
# NOTE: verify the real local-menu table name against the client's install.
# In X3 these integer enums resolve through a menu/message table plus ATEXTRA.
LOCAL_MENUS = {
    (415, 1): "Firm", (415, 2): "Closed", (415, 3): "Cancelled",   # ORDSTA_0
    (1, 1): "No", (1, 2): "Yes",
    (20, 1): "Active", (20, 2): "Not usable", (20, 3): "Obsolete",  # ITMSTA_0
    (700, 1): "Receipt", (700, 2): "Issue", (700, 3): "Adjustment",
    (700, 4): "Transfer in", (700, 5): "Transfer out",
    (861, 1): "Reorder point", (861, 2): "MRP", (861, 3): "Manual",  # REOMODE_0
}

x3["APLSTD"] = [
    {"CHAPTER_0": ch, "CODE_0": co, "LANNUM_0": "ENG", "TEXTE_0": txt}
    for (ch, co), txt in LOCAL_MENUS.items()
]

# ---------------------------------------------------------- items --------
items = []
for i in range(N_ITEMS):
    cat = choice_w(ITEM_CATS, CAT_WEIGHTS)
    ref = f"{cat}-{10000 + i * 7:05d}"
    des = f"{random.choice(PROD_ADJ)} {random.choice(PROD_NOUNS)} {random.choice(PROD_SIZE)}"
    sta = choice_w([1, 2, 3], [0.88, 0.05, 0.07])
    cre = rdate(date(2019, 1, 1), date(2025, 6, 1))
    items.append({
        "ITMREF_0": ref, "cat": cat, "des": des, "ITMSTA_0": sta,
        "BASPRI_0": money(random.uniform(4, 900)), "CREDAT_0": cre,
    })
ITEM_REFS = [it["ITMREF_0"] for it in items]

x3["ITMMASTER"] = []
for it in items:
    base = it["BASPRI_0"]
    x3["ITMMASTER"].append({
        "ITMREF_0": it["ITMREF_0"],
        "ITMDES1_0": it["des"],
        "ITMDES2_0": "" if random.random() < 0.55 else f"Rev {random.choice('ABCD')}",
        "TCLCOD_0": it["cat"],
        "TSICOD_0": random.choice(["STD", "PRM", "ECO"]),
        "TSICOD_1": random.choice(["", "", "OEM", "AFT"]),
        "TSICOD_2": "",
        "STU_0": choice_w(["EA", "BOX", "KG", "M"], [0.75, 0.12, 0.08, 0.05]),
        "ITMSTA_0": it["ITMSTA_0"],
        "BASPRI_0": base,
        "PURBASPRI_0": money(base * random.uniform(0.42, 0.68)),
        "EANCOD_0": "" if random.random() < 0.4 else str(random.randint(10**12, 10**13 - 1)),
        "ITMWEI_0": money(random.uniform(0.05, 42)),
        "CREDAT_0": it["CREDAT_0"],
        "UPDDAT_0": rdate(it["CREDAT_0"], END),
        "CREUSR_0": random.choice(["ADMIN", "JMARTIN", "SPATEL", "DCHEN"]),
        "UPDTICK_0": random.randint(1, 400),
    })

# item x site
x3["ITMFACILIT"] = []
for it in items:
    n_sites = choice_w([1, 2, 3], [0.25, 0.35, 0.40])
    for fcy in random.sample(SITE_CODES, n_sites):
        lt = random.randint(3, 65)
        x3["ITMFACILIT"].append({
            "ITMREF_0": it["ITMREF_0"], "STOFCY_0": fcy,
            "REOMODE_0": choice_w([1, 2, 3], [0.55, 0.30, 0.15]),
            "SAFSTO_0": float(random.randint(0, 400)),
            "REOMINQTY_0": float(random.randint(0, 250)),
            "REOMAXQTY_0": float(random.randint(300, 2500)),
            "LTISUP_0": lt,
            "ABCCLS_0": choice_w(["A", "B", "C"], [0.2, 0.3, 0.5]),
            "UPDTICK_0": random.randint(1, 90),
        })
ITEM_SITE = [(r["ITMREF_0"], r["STOFCY_0"]) for r in x3["ITMFACILIT"]]

# ------------------------------------------------- business partners -----
customers, suppliers = [], []
used_names = set()
for i in range(N_CUSTOMERS):
    while True:
        nm = f"{random.choice(CUST_A)} {random.choice(CUST_B)} {random.choice(CUST_C)}"
        if nm not in used_names:
            used_names.add(nm)
            break
    cn = "CA" if random.random() < 0.18 else "US"
    customers.append({"BPCNUM_0": f"C{1000 + i * 3:05d}", "name": nm, "cry": cn})

for i in range(N_SUPPLIERS):
    nm = f"{random.choice(CUST_A)} {random.choice(['Metals','Castings','Polymers','Import','Forge','Trading'])} {random.choice(CUST_C)}"
    suppliers.append({"BPSNUM_0": f"S{2000 + i * 3:05d}", "name": nm,
                      "lt": random.randint(7, 90)})

CUST_NUMS = [c["BPCNUM_0"] for c in customers]

x3["BPARTNER"] = []
for c in customers:
    x3["BPARTNER"].append({"BPRNUM_0": c["BPCNUM_0"], "BPRNAM_0": c["name"], "BPRNAM_1": "",
                           "BPCFLG_0": 2, "BPSFLG_0": 1, "CRY_0": "USA" if c["cry"] == "US" else "CAN",
                           "CUR_0": "USD" if c["cry"] == "US" else "CAD",
                           "BPRLOG_0": 1, "UPDTICK_0": random.randint(1, 50)})
for s in suppliers:
    x3["BPARTNER"].append({"BPRNUM_0": s["BPSNUM_0"], "BPRNAM_0": s["name"], "BPRNAM_1": "",
                           "BPCFLG_0": 1, "BPSFLG_0": 2, "CRY_0": "USA",
                           "CUR_0": "USD", "BPRLOG_0": 1, "UPDTICK_0": random.randint(1, 50)})

REP_CODES = [f"REP{i:03d}" for i in range(1, N_SALES_REPS + 1)]

x3["BPCUSTOMER"] = []
for c in customers:
    cre = rdate(date(2018, 1, 1), date(2026, 6, 1))
    r1 = random.choice(REP_CODES)
    x3["BPCUSTOMER"].append({
        "BPCNUM_0": c["BPCNUM_0"], "BPCNAM_0": c["name"],
        "BPCGRU_0": choice_w(["NATL", "REGL", "DIST", "OEM"], [.2, .4, .25, .15]),
        "CUR_0": "USD" if c["cry"] == "US" else "CAD",
        "PTE_0": choice_w(["NET30", "NET45", "NET60", "COD"], [.55, .2, .15, .10]),
        "BPCSNC_0": float(random.choice([0, 25000, 50000, 100000, 250000])),
        "OSTCTL_0": choice_w([1, 2], [.85, .15]),
        "ACCCOD_0": "CUS",
        "REP_0": r1,
        "REP_1": random.choice(REP_CODES) if random.random() < 0.18 else "",
        "CREDAT_0": cre, "UPDDAT_0": rdate(cre, END),
        "UPDTICK_0": random.randint(1, 120),
    })

x3["BPSUPPLIER"] = [{"BPSNUM_0": s["BPSNUM_0"], "BPSNAM_0": s["name"], "CUR_0": "USD",
                     "PTE_0": random.choice(["NET30", "NET45"]), "LTI_0": s["lt"],
                     "ACCCOD_0": "SUP", "UPDTICK_0": random.randint(1, 60)}
                    for s in suppliers]

x3["BPADDRESS"] = []
for c in customers:
    pool = US_CITIES if c["cry"] == "US" else CA_CITIES
    n_addr = choice_w([1, 2, 3], [.6, .3, .1])
    for k in range(n_addr):
        city, st, zp = random.choice(pool)
        x3["BPADDRESS"].append({
            "BPATYP_0": 1, "BPANUM_0": c["BPCNUM_0"],
            "BPAADD_0": "MAIN" if k == 0 else f"SHIP{k}",
            "BPADES_0": "Head Office" if k == 0 else "Ship To",
            "ADDLIG_0": f"{random.randint(100, 9800)} {random.choice(['Industrial','Commerce','Enterprise','Ridge','Foundry'])} {random.choice(['Blvd','Dr','Pkwy','Rd'])}",
            "ADDLIG_1": "" if random.random() < .8 else f"Suite {random.randint(100,900)}",
            "CTY_0": city, "SAT_0": st, "POSCOD_0": zp,
            "CRY_0": "USA" if c["cry"] == "US" else "CAN",
            "TEL_0": f"({random.randint(200,989)}) {random.randint(200,999)}-{random.randint(1000,9999)}",
        })

# ----------------------------------------------------- sales orders -----
PRICE_BY_ITEM = {m["ITMREF_0"]: m["BASPRI_0"] for m in x3["ITMMASTER"]}
ITEM_DES = {m["ITMREF_0"]: m["ITMDES1_0"] for m in x3["ITMMASTER"]}
ITEMS_BY_SITE = {}
for itm, fcy in ITEM_SITE:
    ITEMS_BY_SITE.setdefault(fcy, []).append(itm)


def seasonal_weight(d):
    m = d.month
    return 1.0 + 0.35 * math.sin((m - 3) / 12 * 2 * math.pi) + 0.0006 * (d - START).days


order_dates = []
cur = START
while cur <= END:
    if cur.weekday() < 5:
        order_dates.append(cur)
    cur += timedelta(days=1)
date_weights = [seasonal_weight(d) for d in order_dates]

x3["SORDER"], x3["SORDERQ"], x3["SORDERP"] = [], [], []
order_index = {}          # soh -> dict of header facts, reused downstream
order_lines = []          # (soh, line, item, qty, price, date, fcy, shipped)

for i in range(N_ORDERS):
    d = random.choices(order_dates, weights=date_weights, k=1)[0]
    cust = random.choice(customers)
    fcy = "CA001" if cust["cry"] == "CA" else random.choice(["US001", "US002"])
    soh = f"SO{fcy[:2]}{d.year % 100:02d}{i:06d}"
    age = (TODAY - d).days
    if age > 45:
        sta = choice_w([1, 2, 3], [.03, .93, .04])
    elif age > 10:
        sta = choice_w([1, 2, 3], [.35, .60, .05])
    else:
        sta = choice_w([1, 2, 3], [.85, .10, .05])
    shipped = (sta == 2)
    shidat = d + timedelta(days=random.randint(1, 21)) if shipped else NULL_DATE
    rep = random.choice(REP_CODES)
    n_lines = choice_w([1, 2, 3, 4, 5, 8], [.30, .25, .18, .12, .09, .06])
    pool = ITEMS_BY_SITE.get(fcy, ITEM_REFS)
    total = 0.0

    for ln in range(n_lines):
        itm = random.choice(pool)
        qty = float(random.choice([1, 2, 4, 5, 10, 12, 24, 25, 50, 100, 144, 250]))
        gross = PRICE_BY_ITEM.get(itm, 50.0)
        disc = choice_w([0.0, 2.5, 5.0, 10.0, 15.0], [.45, .15, .20, .15, .05])
        net = money(gross * (1 - disc / 100))
        line_amt = money(net * qty)
        total += line_amt
        lineno = (ln + 1) * 1000

        x3["SORDERQ"].append({
            "SOHNUM_0": soh, "SOPLIN_0": lineno, "SOQSEQ_0": 1,
            "ITMREF_0": pad(itm, 20),            # CHAR-padded on purpose
            "STOFCY_0": fcy, "QTY_0": qty,
            "DEMDLVDAT_0": d + timedelta(days=random.randint(2, 40)),
            "SHTQTY_0": 0.0 if shipped else round(qty * random.choice([0, 0, 0, 0.5]), 2),
            "UOM_0": "EA", "UPDTICK_0": random.randint(1, 20),
        })
        x3["SORDERP"].append({
            "SOHNUM_0": soh, "SOPLIN_0": lineno, "SOPSEQ_0": 1,
            "ITMREF_0": pad(itm, 20),
            "ITMDES1_0": ITEM_DES.get(itm, ""),
            "GROPRI_0": gross, "NETPRI_0": net,
            "DISCRGVAL1_0": disc, "AMTNOTLIN_0": line_amt,
            "VAT1_0": "STD", "UPDTICK_0": random.randint(1, 20),
        })
        order_lines.append((soh, lineno, itm, qty, net, d, fcy, shipped))

    x3["SORDER"].append({
        "SOHNUM_0": soh, "SALFCY_0": fcy, "STOFCY_0": fcy,
        "BPCORD_0": pad(cust["BPCNUM_0"], 15),   # CHAR-padded on purpose
        "BPCINV_0": cust["BPCNUM_0"],
        "ORDDAT_0": d, "SHIDAT_0": shidat,
        "CUR_0": "CAD" if cust["cry"] == "CA" else "USD",
        "ORDSTA_0": sta, "REP_0": rep, "REP_1": "",
        "TOTLINAMT_0": money(total),
        "ORDINVSTA_0": choice_w([1, 2, 3], [.15, .10, .75] if shipped else [.9, .05, .05]),
        "CREUSR_0": random.choice(["JMARTIN", "SPATEL", "DCHEN", "RKAUR", "EDI"]),
        "CREDAT_0": d, "UPDDAT_0": d + timedelta(days=random.randint(0, 30)),
        "UPDTICK_0": random.randint(1, 40),
    })
    order_index[soh] = {"cust": cust, "date": d, "fcy": fcy, "sta": sta,
                        "shipped": shipped, "shidat": shidat, "total": money(total),
                        "rep": rep}

# ---------------------------------------------------------- invoices ----
x3["SINVOICEV"], x3["SINVOICED"] = [], []
inv_seq = 0
lines_by_order = {}
for (soh, lineno, itm, qty, net, d, fcy, shipped) in order_lines:
    lines_by_order.setdefault(soh, []).append((lineno, itm, qty, net))

for soh, h in order_index.items():
    if not h["shipped"] or random.random() < 0.06:      # some shipped orders uninvoiced
        continue
    inv_seq += 1
    num = f"SI{h['fcy'][:2]}{h['date'].year % 100:02d}{inv_seq:06d}"
    invdat = h["shidat"] + timedelta(days=random.randint(0, 6))
    tot = 0.0
    for k, (lineno, itm, qty, net) in enumerate(lines_by_order.get(soh, [])):
        amt = money(net * qty)
        tot += amt
        x3["SINVOICED"].append({
            "NUM_0": num, "SIDLIN_0": (k + 1) * 1000, "ITMREF_0": itm,
            "ITMDES1_0": "", "QTY_0": qty, "NETPRI_0": net,
            "AMTNOTLIN_0": amt, "SOHNUM_0": soh, "SOPLIN_0": lineno,
            "STOFCY_0": h["fcy"],
        })
    tax = money(tot * (0.0825 if h["fcy"].startswith("US") else 0.13))
    x3["SINVOICEV"].append({
        "NUM_0": num, "SIVTYP_0": "SIN", "INVDAT_0": invdat,
        "BPR_0": h["cust"]["BPCNUM_0"], "SALFCY_0": h["fcy"],
        "CUR_0": "CAD" if h["cust"]["cry"] == "CA" else "USD",
        "AMTNOTLIN_0": money(tot), "AMTTAXLIN_0": tax,
        "AMTATILIN_0": money(tot + tax),
        "INVSTA_0": choice_w([1, 2], [.12, .88]),
        "PAYDAT_0": invdat + timedelta(days=random.choice([28, 30, 31, 45, 47, 62, 90]))
        if random.random() < 0.86 else NULL_DATE,
        "ACCDAT_0": invdat, "UPDTICK_0": random.randint(1, 15),
    })

# ------------------------------------------------------ stock + journal --
x3["STOCK"] = []
for itm, fcy in ITEM_SITE:
    for lot_i in range(choice_w([1, 2, 3], [.6, .3, .1])):
        x3["STOCK"].append({
            "STOFCY_0": fcy, "ITMREF_0": itm,
            "LOT_0": f"L{random.randint(100000, 999999)}",
            "LOC_0": f"{random.choice('ABCDE')}{random.randint(1,24):02d}-{random.randint(1,6)}",
            "QTYSTU_0": float(random.randint(0, 3000)),
            "STA_0": choice_w(["A", "Q", "R"], [.92, .05, .03]),
            "OWNER_0": fcy, "UPDTICK_0": random.randint(1, 200),
        })

x3["STOJOU"] = []
rowid = 0
for (soh, lineno, itm, qty, net, d, fcy, shipped) in order_lines:
    if not shipped:
        continue
    rowid += 1
    x3["STOJOU"].append({
        "ROWID": rowid, "ITMREF_0": pad(itm, 20), "STOFCY_0": fcy,
        "IPTDAT_0": order_index[soh]["shidat"], "TRSTYP_0": 2,
        "QTYSTU_0": -qty, "VCRNUM_0": soh, "VCRTYP_0": "SDH",
        "LOT_0": f"L{random.randint(100000, 999999)}",
        "CREUSR_0": "WMS", "UPDTICK_0": 1,
    })
for _ in range(6000):                                   # receipts + adjustments
    itm, fcy = random.choice(ITEM_SITE)
    rowid += 1
    t = choice_w([1, 3, 4, 5], [.72, .16, .06, .06])
    q = float(random.randint(10, 1200)) * (1 if t in (1, 4) else random.choice([1, -1]))
    x3["STOJOU"].append({
        "ROWID": rowid, "ITMREF_0": pad(itm, 20), "STOFCY_0": fcy,
        "IPTDAT_0": rdate(), "TRSTYP_0": t, "QTYSTU_0": q,
        "VCRNUM_0": f"{'PTH' if t == 1 else 'ADJ'}{random.randint(100000, 999999)}",
        "VCRTYP_0": "PTH" if t == 1 else "ADJ",
        "LOT_0": f"L{random.randint(100000, 999999)}",
        "CREUSR_0": random.choice(["WMS", "ADMIN", "RKAUR"]), "UPDTICK_0": 1,
    })

# --------------------------------------------------- purchase orders ----
x3["PORDER"], x3["PORDERQ"] = [], []
for i in range(1400):
    d = rdate()
    s = random.choice(suppliers)
    fcy = random.choice(SITE_CODES)
    poh = f"PO{fcy[:2]}{d.year % 100:02d}{i:06d}"
    x3["PORDER"].append({
        "POHNUM_0": poh, "POHFCY_0": fcy, "BPSNUM_0": s["BPSNUM_0"],
        "ORDDAT_0": d, "ORDSTA_0": choice_w([1, 2, 3], [.2, .75, .05]),
        "CUR_0": "USD", "CREUSR_0": random.choice(["PBUYER", "ADMIN"]),
        "UPDTICK_0": random.randint(1, 20),
    })
    for ln in range(choice_w([1, 2, 3, 6], [.4, .3, .2, .1])):
        itm = random.choice(ITEM_REFS)
        q = float(random.randint(50, 2000))
        exp = d + timedelta(days=s["lt"] + random.randint(-5, 30))
        rcp = q * choice_w([1.0, 0.0, 0.85], [.7, .2, .1])
        x3["PORDERQ"].append({
            "POHNUM_0": poh, "POPLIN_0": (ln + 1) * 1000, "POQSEQ_0": 1,
            "ITMREF_0": itm, "POHFCY_0": fcy, "QTYUOM_0": q,
            "EXTRCPDAT_0": exp,
            "RCPQTY_0": rcp,
            "RCPDAT_0": exp + timedelta(days=random.randint(-3, 18)) if rcp > 0 else NULL_DATE,
            "NETPRI_0": money(PRICE_BY_ITEM.get(itm, 50) * random.uniform(.4, .65)),
            "UPDTICK_0": random.randint(1, 20),
        })

# ------------------------------------------------------------- GL -------
x3["GACCENTRY"], x3["GACCENTRYD"] = [], []
gnum = 0
for v in x3["SINVOICEV"]:
    gnum += 1
    num = f"GL{gnum:08d}"
    cpy = "GLBCA" if v["SALFCY_0"] == "CA001" else "GLBUS"
    x3["GACCENTRY"].append({
        "NUM_0": num, "TYP_0": "SIH", "JOU_0": "SAL", "CPY_0": cpy,
        "FCY_0": v["SALFCY_0"], "ACCDAT_0": v["ACCDAT_0"], "CUR_0": v["CUR_0"],
        "DES_0": f"Invoice {v['NUM_0']}", "VCRNUM_0": v["NUM_0"],
        "STA_0": 3, "UPDTICK_0": 1,
    })
    rows = [("11100", 1, v["AMTATILIN_0"]), ("41000", -1, v["AMTNOTLIN_0"]),
            ("22300", -1, v["AMTTAXLIN_0"])]
    for k, (acc, sns, amt) in enumerate(rows):
        x3["GACCENTRYD"].append({
            "NUM_0": num, "LIN_0": (k + 1) * 1000, "ACC_0": acc, "SNS_0": sns,
            "AMTCUR_0": money(amt), "AMTLOC_0": money(amt * (0.74 if v["CUR_0"] == "CAD" else 1.0)),
            "BPR_0": v["BPR_0"], "CPY_0": cpy, "FCY_0": v["SALFCY_0"],
            "DSP_0": "", "ACCDAT_0": v["ACCDAT_0"],
        })

# --------------------------------------------------------- ATEXTRA ------
x3["ATEXTRA"] = []
for m in random.sample(x3["ITMMASTER"], 120):
    x3["ATEXTRA"].append({"CODFIC_0": "ITMMASTER", "ZONE_0": "DES1AXX", "LANNUM_0": "FRA",
                          "IDENT1_0": m["ITMREF_0"], "IDENT2_0": "",
                          "TEXTE_0": "Piece " + m["ITMDES1_0"].lower()})
for (ch, co), txt in LOCAL_MENUS.items():
    x3["ATEXTRA"].append({"CODFIC_0": "APLSTD", "ZONE_0": "LNGDES", "LANNUM_0": "FRA",
                          "IDENT1_0": str(ch), "IDENT2_0": str(co), "TEXTE_0": txt + " (FR)"})

# ------------------------------------------------------ sales reps ------
REP_PEOPLE = []
for i, code in enumerate(REP_CODES):
    f, l = FIRST[i % len(FIRST)], LAST[(i * 3) % len(LAST)]
    REP_PEOPLE.append({"code": code, "first": f, "last": l,
                       "fcy": SITE_CODES[i % 3]})
x3["REPRESENT"] = [{"REPNUM_0": r["code"], "REPNAM_0": f"{r['last'].upper()} {r['first'].upper()}",
                    "FCY_0": r["fcy"], "REPTYP_0": 1, "UPDTICK_0": 1} for r in REP_PEOPLE]

# =========================================================================
#  HUBSPOT   (API/connector-shaped; properties arrive as strings)
# =========================================================================
hs = {}
OWNERS = []
for i, r in enumerate(REP_PEOPLE[:22]):
    OWNERS.append({"id": str(90000000 + i * 137), "email":
                   f"{r['first'].lower()}.{r['last'].lower()}@globexdist.com",
                   "first_name": r["first"], "last_name": r["last"],
                   "user_id": str(40000 + i), "archived": False,
                   "created_at": date(2023, 1, 15), "updated_at": rdate()})
hs["owner"] = OWNERS
OWNER_IDS = [o["id"] for o in OWNERS]

PIPELINES = [("default", "Sales Pipeline"), ("p_oem", "OEM Programs")]
STAGES = [("appointmentscheduled", "Discovery", 1, False, False),
          ("qualifiedtobuy", "Qualified", 2, False, False),
          ("presentationscheduled", "Proposal Sent", 3, False, False),
          ("decisionmakerboughtin", "Negotiation", 4, False, False),
          ("contractsent", "Contract Sent", 5, False, False),
          ("closedwon", "Closed Won", 6, True, True),
          ("closedlost", "Closed Lost", 7, True, False)]
hs["pipeline_stage"] = [{"pipeline_id": p, "pipeline_label": pl, "stage_id": s,
                         "stage_label": sl, "display_order": o,
                         "is_closed": c, "is_closed_won": w}
                        for p, pl in PIPELINES for s, sl, o, c, w in STAGES]

# ~78% of HubSpot companies correspond to a real X3 customer, by NAME only.
hs_companies = []
matched = random.sample(customers, int(N_HS_COMPANIES * 0.78))
for i in range(N_HS_COMPANIES):
    cid = str(11000000000 + i * 991)
    if i < len(matched):
        src = matched[i]
        nm = src["name"]
        # HubSpot names drift from ERP names: suffix noise, casing, punctuation
        r = random.random()
        if r < 0.22:
            nm = nm.replace(" Inc", ", Inc.").replace(" LLC", ", LLC")
        elif r < 0.32:
            nm = nm.rsplit(" ", 1)[0]
        elif r < 0.38:
            nm = nm.upper()
        cry = src["cry"]
    else:
        nm = f"{random.choice(CUST_A)} {random.choice(CUST_B)} {random.choice(CUST_C)}"
        cry = random.choice(["US", "US", "CA"])
    dom = "".join(ch for ch in nm.lower() if ch.isalnum())[:18] + ".com"
    created = rdate(date(2022, 1, 1), END)
    hs_companies.append({
        "id": cid, "name": nm, "domain": dom if random.random() < .88 else None,
        "industry": random.choice(["MACHINERY", "INDUSTRIAL_AUTOMATION", "OIL_ENERGY",
                                   "CONSTRUCTION", "AUTOMOTIVE", "MINING_METALS", None]),
        "country": "United States" if cry == "US" else "Canada",
        "numberofemployees": str(random.choice([12, 45, 120, 300, 850, 2400]))
        if random.random() < .7 else None,
        "annualrevenue": str(random.choice([2500000, 12000000, 48000000, 190000000]))
        if random.random() < .5 else None,
        "hubspot_owner_id": random.choice(OWNER_IDS) if random.random() < .9 else None,
        "createdate": created,
        "hs_lastmodifieddate": rdate(created, END),
        "archived": random.random() < 0.04,
    })
hs["company"] = hs_companies
HS_COMP_IDS = [c["id"] for c in hs_companies]

hs_contacts = []
for i in range(N_HS_CONTACTS):
    f, l = random.choice(FIRST), random.choice(LAST)
    comp = random.choice(hs_companies)
    dom = comp["domain"] or "example.com"
    email = f"{f.lower()}.{l.lower()}@{dom}"
    if random.random() < 0.05:
        email = None                                   # missing email
    created = rdate(date(2022, 1, 1), END)
    hs_contacts.append({
        "id": str(12000000000 + i * 773), "email": email,
        "firstname": f, "lastname": l,
        "jobtitle": random.choice(["Buyer", "Maintenance Manager", "Plant Manager",
                                   "Procurement Lead", "Engineer", "Owner", None]),
        "phone": f"+1{random.randint(2000000000, 9899999999)}" if random.random() < .7 else None,
        "lifecyclestage": choice_w(["subscriber", "lead", "marketingqualifiedlead",
                                    "salesqualifiedlead", "opportunity", "customer"],
                                   [.12, .28, .14, .16, .12, .18]),
        "hs_lead_status": random.choice(["NEW", "OPEN", "IN_PROGRESS", "UNQUALIFIED", None]),
        "hubspot_owner_id": random.choice(OWNER_IDS) if random.random() < .8 else None,
        "associatedcompanyid": comp["id"],
        "createdate": created, "lastmodifieddate": rdate(created, END),
        "archived": random.random() < 0.03,
    })
# duplicate contacts: same human, two records
for c in random.sample(hs_contacts, 40):
    d = dict(c)
    d["id"] = str(int(c["id"]) + 1)
    d["email"] = (c["email"] or "").replace(".", "_", 1) or None
    d["createdate"] = rdate(c["createdate"], END)
    hs_contacts.append(d)
hs["contact"] = hs_contacts

shipped_orders = [s for s, h in order_index.items() if h["shipped"]]
hs_deals, hs_stage_hist = [], []
for i in range(N_HS_DEALS):
    comp = random.choice(hs_companies)
    created = rdate(date(2023, 6, 1), END)
    stage = choice_w([s[0] for s in STAGES], [.10, .12, .14, .10, .08, .30, .16])
    is_closed = stage in ("closedwon", "closedlost")
    amt = round(random.lognormvariate(9.6, 0.9), 2)
    closedate = rdate(created, min(END, created + timedelta(days=240))) if is_closed \
        else created + timedelta(days=random.randint(10, 200))
    # the ERP handoff: populated on ~60% of won deals, sometimes malformed
    erp = None
    if stage == "closedwon" and random.random() < 0.60 and shipped_orders:
        so = random.choice(shipped_orders)
        rr = random.random()
        erp = so if rr < .72 else (so.lower() if rr < .84 else
                                   (f"{so} / {random.choice(shipped_orders)}" if rr < .93 else so[2:]))
    did = str(13000000000 + i * 617)
    hs_deals.append({
        "id": did, "dealname": f"{comp['name']} - {random.choice(['Q1','Q2','Q3','Q4'])} "
                               f"{random.choice(['Resupply','Retrofit','New Line','Blanket PO','Expansion'])}",
        "amount": f"{amt}",                       # string, as the API returns it
        "dealstage": stage, "pipeline": choice_w([p[0] for p in PIPELINES], [.85, .15]),
        "closedate": closedate, "createdate": created,
        "hs_lastmodifieddate": rdate(created, END),
        "hubspot_owner_id": random.choice(OWNER_IDS),
        "dealtype": random.choice(["newbusiness", "existingbusiness"]),
        "hs_is_closed_won": stage == "closedwon",
        "hs_deal_stage_probability": str(round(random.uniform(0.05, 0.95), 2)),
        "erp_order_number": erp,                  # custom property
        "associated_company_id": comp["id"],
        "archived": random.random() < 0.02,
    })
    seq = [s[0] for s in STAGES if not s[3]]
    idx = seq.index(stage) if stage in seq else len(seq)
    t = created
    for s in seq[:idx] + ([stage] if is_closed else [stage]):
        hs_stage_hist.append({"deal_id": did, "stage": s, "changed_at": t,
                              "changed_by_owner_id": random.choice(OWNER_IDS)})
        t = t + timedelta(days=random.randint(2, 45))
hs["deal"] = hs_deals
hs["deal_stage_history"] = hs_stage_hist

CONTACTS_BY_COMPANY = {}
for c in hs_contacts:
    CONTACTS_BY_COMPANY.setdefault(c["associatedcompanyid"], []).append(c)

hs["association"] = []
for d in hs_deals:
    hs["association"].append({"from_object_type": "deal", "from_id": d["id"],
                              "to_object_type": "company", "to_id": d["associated_company_id"],
                              "association_type": "deal_to_company"})
    pool_c = CONTACTS_BY_COMPANY.get(d["associated_company_id"], [])
    for c in random.sample(pool_c, min(len(pool_c), random.randint(0, 2))):
        hs["association"].append({"from_object_type": "deal", "from_id": d["id"],
                                  "to_object_type": "contact", "to_id": c["id"],
                                  "association_type": "deal_to_contact"})
for c in hs_contacts:
    hs["association"].append({"from_object_type": "contact", "from_id": c["id"],
                              "to_object_type": "company", "to_id": c["associatedcompanyid"],
                              "association_type": "contact_to_company"})

hs["engagement"] = []
for i in range(3000):
    d = random.choice(hs_deals)
    ts = rdate(d["createdate"], END)
    hs["engagement"].append({
        "id": str(14000000000 + i * 331),
        "type": choice_w(["EMAIL", "CALL", "MEETING", "NOTE", "TASK"], [.45, .22, .12, .13, .08]),
        "created_at": ts, "owner_id": d["hubspot_owner_id"],
        "associated_deal_id": d["id"], "associated_company_id": d["associated_company_id"],
        "body_preview": random.choice(["Follow up on pricing", "Left voicemail",
                                       "Sent revised quote", "Site visit scheduled",
                                       "Awaiting PO", "Discussed lead times"]),
    })

# =========================================================================
#  PAYCOM   (export-shaped: no queryable backend exists; dates are strings)
# =========================================================================
pc = {}
DEPTS = [("100", "Sales"), ("200", "Warehouse"), ("300", "Operations"),
         ("400", "Finance"), ("500", "Customer Service"), ("600", "Executive")]
EARN_CODES = [("REG", "Regular", "50100"), ("OT", "Overtime", "50110"),
              ("BON", "Bonus", "50120"), ("COMM", "Commission", "50130"),
              ("PTO", "Paid Time Off", "50140"), ("HOL", "Holiday", "50140")]
DED_CODES = [("MED", "Medical", "21500"), ("DEN", "Dental", "21500"),
             ("401K", "401(k) Deferral", "21600"), ("HSA", "HSA", "21500"),
             ("GARN", "Garnishment", "21700")]
TAX_CODES = [("FIT", "Federal Income Tax"), ("SS", "Social Security"),
             ("MED", "Medicare"), ("SUI", "State Unemployment"),
             ("SIT", "State Income Tax")]


def us(d):
    return d.strftime("%m/%d/%Y")


employees = []
for i in range(N_EMPLOYEES):
    if i < N_SALES_REPS:
        r = REP_PEOPLE[i]
        f, l, fcy, dept = r["first"], r["last"], r["fcy"], "100"
    else:
        f, l = random.choice(FIRST), random.choice(LAST)
        fcy = random.choice(SITE_CODES)
        dept = choice_w([d[0] for d in DEPTS], [.05, .40, .22, .10, .18, .05])
    hire = rdate(date(2016, 1, 1), date(2026, 7, 1))
    term = None
    if random.random() < 0.17:
        term = rdate(hire + timedelta(days=120), TODAY)
        if term > TODAY:
            term = None
    pay_type = "S" if dept in ("100", "400", "600") or random.random() < .2 else "H"
    employees.append({
        "employee_code": f"{100000 + i * 13}", "first": f, "last": l,
        "fcy": fcy, "dept": dept, "hire": hire, "term": term, "pay_type": pay_type,
        "rate": money(random.uniform(52000, 165000)) if pay_type == "S"
        else money(random.uniform(17.5, 38.0)),
    })

pc["employee"] = [{
    "employee_code": e["employee_code"],
    "ee_id": f"EE{e['employee_code']}",
    "legal_first_name": e["first"], "legal_last_name": e["last"],
    "preferred_name": e["first"] if random.random() < .9 else e["first"][:3],
    "work_email": f"{e['first'].lower()}.{e['last'].lower()}@globexdist.com",
    "hire_date": us(e["hire"]),
    "rehire_date": "",
    "termination_date": us(e["term"]) if e["term"] else "",
    "employment_status": "Terminated" if e["term"] else "Active",
    "department_code": e["dept"],
    "department_desc": dict(DEPTS)[e["dept"]],
    "location_code": PAYCOM_LOC[e["fcy"]],           # NOT equal to Sage FCY_0
    "position_title": random.choice(["Account Executive", "Warehouse Associate",
                                     "Inventory Analyst", "AP Specialist",
                                     "CSR", "Operations Supervisor", "Buyer"]),
    "pay_type": e["pay_type"],
    "annual_salary": f"{e['rate']:.2f}" if e["pay_type"] == "S" else "",
    "hourly_rate": f"{e['rate']:.4f}" if e["pay_type"] == "H" else "",
    "ssn_last4": f"{random.randint(0, 9999):04d}",
    "manager_ee_id": "",
} for e in employees]

periods = []
p = date(2024, 7, 5)
while p <= date(2026, 8, 28):
    periods.append(p)
    p += timedelta(days=14)

pc["check"], pc["earning_detail"], pc["deduction_detail"], pc["tax_detail"] = [], [], [], []
chk = 0
for pay_date in periods:
    ps = pay_date - timedelta(days=13)
    pe = pay_date - timedelta(days=0)
    for e in employees:
        if e["hire"] > pe or (e["term"] and e["term"] < ps):
            continue
        chk += 1
        cid = f"CHK{chk:08d}"
        earns = []
        if e["pay_type"] == "S":
            base = money(e["rate"] / 26)
            earns.append(("REG", 80.0, base))
        else:
            hrs = round(random.uniform(64, 80), 2)
            earns.append(("REG", hrs, money(hrs * e["rate"])))
            if random.random() < 0.34:
                ot = round(random.uniform(1, 14), 2)
                earns.append(("OT", ot, money(ot * e["rate"] * 1.5)))
        if e["dept"] == "100" and random.random() < 0.7:
            earns.append(("COMM", 0.0, money(random.uniform(200, 6500))))
        if random.random() < 0.10:
            earns.append(("PTO", 8.0, money(8 * (e["rate"] / 2080 if e["pay_type"] == "S"
                                                 else e["rate"]))))
        gross = money(sum(a for _, _, a in earns))
        deds, taxes = [], []
        for code, _, _ in DED_CODES:
            if random.random() < (0.85 if code in ("MED", "401K") else 0.25):
                amt = money(gross * random.uniform(0.01, 0.06))
                deds.append((code, amt, money(amt * random.uniform(0.5, 1.8))))
        for code, _ in TAX_CODES:
            rate = {"FIT": .12, "SS": .062, "MED": .0145, "SUI": .006, "SIT": .04}[code]
            taxes.append((code, money(gross * rate * random.uniform(.85, 1.15)),
                          money(gross * rate * random.uniform(0, 1.0))))
        net = money(gross - sum(a for _, a, _ in deds) - sum(a for _, a, _ in taxes))
        pc["check"].append({
            "check_id": cid, "employee_code": e["employee_code"],
            "check_date": us(pay_date), "period_start": us(ps), "period_end": us(pe),
            "check_number": f"{500000 + chk}", "gross_pay": f"{gross:.2f}",
            "net_pay": f"{net:.2f}", "check_type": "Regular",
            "location_code": PAYCOM_LOC[e["fcy"]], "department_code": e["dept"],
        })
        for code, hrs, amt in earns:
            pc["earning_detail"].append({
                "check_id": cid, "employee_code": e["employee_code"],
                "earning_code": code, "earning_desc": dict((c, d) for c, d, _ in EARN_CODES)[code],
                "hours": f"{hrs:.2f}", "amount": f"{amt:.2f}",
                "labor_allocation_code": f"{PAYCOM_LOC[e['fcy']]}-{e['dept']}",
            })
        for code, ee, er in deds:
            pc["deduction_detail"].append({
                "check_id": cid, "employee_code": e["employee_code"],
                "deduction_code": code, "ee_amount": f"{ee:.2f}", "er_amount": f"{er:.2f}"})
        for code, ee, er in taxes:
            pc["tax_detail"].append({
                "check_id": cid, "employee_code": e["employee_code"],
                "tax_code": code, "ee_amount": f"{ee:.2f}", "er_amount": f"{er:.2f}"})

pc["gl_mapping"] = ([{"code_type": "EARNING", "code": c, "description": d, "gl_account": g}
                     for c, d, g in EARN_CODES] +
                    [{"code_type": "DEDUCTION", "code": c, "description": d, "gl_account": g}
                     for c, d, g in DED_CODES])

# =========================================================================
#  NETSTOCK   (inferred shape; reads item/location keys from the ERP)
# =========================================================================
ns = {}
LAST_SYNC = date(2026, 9, 2)
ns["supplier"] = [{"supplier_code": s["BPSNUM_0"], "supplier_name": s["name"],
                   "lead_time_days": s["lt"], "min_order_value": float(random.choice([0, 500, 2500])),
                   "source_system": "SAGEX3"} for s in suppliers]

ns_pairs = [(i, f) for i, f in ITEM_SITE if random.random() < 0.97]
for _ in range(35):                                   # orphans: not in current ITMMASTER
    ns_pairs.append((f"FG-{random.randint(90000, 99999)}", random.choice(SITE_CODES)))

ns["item_location"] = []
for itm, fcy in ns_pairs:
    ns["item_location"].append({
        "item_code": itm, "location_code": fcy,
        "description": ITEM_DES.get(itm, "UNKNOWN - not in ERP master"),
        "abc_class": choice_w(["A", "B", "C"], [.2, .3, .5]),
        "xyz_class": choice_w(["X", "Y", "Z"], [.35, .4, .25]),
        "policy": choice_w(["MIN_MAX", "ROP", "FORECAST"], [.3, .4, .3]),
        "lead_time_days": random.randint(3, 75),
        "safety_stock_qty": float(random.randint(0, 500)),
        "reorder_point_qty": float(random.randint(50, 1500)),
        "min_order_qty": float(random.choice([1, 10, 25, 50, 100])),
        "supplier_code": random.choice(suppliers)["BPSNUM_0"],
        "on_hand_qty": float(random.randint(0, 4000)),
        "on_order_qty": float(random.randint(0, 1500)),
        "excess_value": money(random.uniform(0, 45000)) if random.random() < .3 else 0.0,
        "stockout_risk": choice_w(["LOW", "MEDIUM", "HIGH"], [.6, .28, .12]),
        "last_sync_at": LAST_SYNC,
    })

ns["forecast"], ns["forecast_accuracy"] = [], []
months = []
m = date(2025, 9, 1)
for k in range(24):
    months.append(m)
    y, mm = divmod(m.month, 12)
    m = date(m.year + y, mm + 1, 1)
for itm, fcy in ns_pairs:
    lvl = random.uniform(5, 400)
    for per in months:
        fq = round(max(0.0, lvl * (1 + 0.25 * math.sin(per.month / 12 * 2 * math.pi))
                       * random.uniform(.7, 1.3)), 2)
        ns["forecast"].append({
            "item_code": itm, "location_code": fcy, "period_start": per,
            "period_type": "MONTH", "forecast_qty": fq,
            "forecast_method": choice_w(["CROSTON", "HOLT_WINTERS", "MOVING_AVG", "MANUAL"],
                                        [.2, .35, .35, .10]),
            "generated_at": LAST_SYNC,
        })
        if per < date(2026, 9, 1):
            act = round(max(0.0, fq * random.uniform(.45, 1.65)), 2)
            ns["forecast_accuracy"].append({
                "item_code": itm, "location_code": fcy, "period_start": per,
                "forecast_qty": fq, "actual_qty": act,
                "abs_pct_error": round(abs(act - fq) / fq * 100, 2) if fq else None,
            })

ns["replenishment_recommendation"] = []
for k, (itm, fcy) in enumerate(random.sample(ns_pairs, min(900, len(ns_pairs)))):
    ns["replenishment_recommendation"].append({
        "recommendation_id": f"REC{k:07d}", "item_code": itm, "location_code": fcy,
        "recommended_qty": float(random.randint(25, 2000)),
        "recommended_order_date": TODAY + timedelta(days=random.randint(-20, 30)),
        "required_date": TODAY + timedelta(days=random.randint(10, 90)),
        "supplier_code": random.choice(suppliers)["BPSNUM_0"],
        "status": choice_w(["OPEN", "ACCEPTED", "REJECTED", "EXPIRED"], [.5, .3, .1, .1]),
        "erp_po_number": random.choice([r["POHNUM_0"] for r in x3["PORDER"]])
        if random.random() < .25 else None,
        "generated_at": LAST_SYNC,
    })

# =========================================================================
#  PANGEA   (shipments - INFERRED shape, generic freight platform)
# =========================================================================
pg = {}
CARRIERS = [("FDEG", "FedEx Ground", "PARCEL"), ("UPSN", "UPS", "PARCEL"),
            ("ODFL", "Old Dominion", "LTL"), ("SAIA", "Saia LTL Freight", "LTL"),
            ("XPOL", "XPO Logistics", "LTL"), ("CHRW", "C.H. Robinson", "TL"),
            ("PURO", "Purolator", "PARCEL")]
pg["carrier"] = [{"scac": s, "carrier_name": n, "mode": m} for s, n, m in CARRIERS]

EVENTS = [("PU", "Picked up"), ("IT", "In transit"), ("AR", "Arrived at facility"),
          ("DP", "Departed facility"), ("OD", "Out for delivery"),
          ("DL", "Delivered"), ("EX", "Exception - weather delay"),
          ("AT", "Attempted delivery")]

pg["shipment"], pg["shipment_leg"], pg["tracking_event"], pg["charge"] = [], [], [], []
sh = 0
for soh in shipped_orders:
    if random.random() < 0.08:
        continue                                       # not every order ships via Pangea
    h = order_index[soh]
    sh += 1
    sid = f"PGA{sh:08d}"
    scac, cname, mode = random.choice(CARRIERS)
    cust = h["cust"]
    pool = US_CITIES if cust["cry"] == "US" else CA_CITIES
    city, st, zp = random.choice(pool)
    ship_dt = h["shidat"]
    transit = random.randint(1, 9)
    delivered = ship_dt + timedelta(days=transit)
    status = "DELIVERED" if delivered <= TODAY else "IN_TRANSIT"
    if random.random() < 0.03:
        status = "EXCEPTION"
    # the ERP handoff: reference is usually the sales order, sometimes not
    r = random.random()
    ref = soh if r < .85 else (None if r < .92 else f"CUST-PO-{random.randint(10000,99999)}")
    weight = round(random.uniform(2, 4200), 1)
    cost = money(weight * random.uniform(0.18, 1.4) + random.uniform(8, 90))
    pg["shipment"].append({
        "shipment_id": sid, "reference_number": ref,
        "customer_name": cust["name"],
        "carrier_scac": scac, "service_level": random.choice(
            ["GROUND", "2DAY", "STANDARD_LTL", "GUARANTEED", "ECONOMY"]),
        "mode": mode,
        "origin_site_code": h["fcy"],
        "dest_city": city, "dest_state": st, "dest_postal": zp,
        "dest_country": "US" if cust["cry"] == "US" else "CA",
        "ship_date": ship_dt,
        "estimated_delivery_date": ship_dt + timedelta(days=transit + random.randint(-1, 2)),
        "delivered_date": delivered if status == "DELIVERED" else None,
        "status": status,
        "weight_lb": weight, "piece_count": random.randint(1, 24),
        "total_cost_usd": cost,
        "created_at": ship_dt,
    })
    n_legs = 1 if mode == "PARCEL" else random.choice([1, 2, 2, 3])
    prev = h["fcy"]
    for lg in range(n_legs):
        dst = city if lg == n_legs - 1 else random.choice(pool)[0]
        dep = ship_dt + timedelta(days=lg)
        pg["shipment_leg"].append({
            "shipment_id": sid, "leg_seq": lg + 1, "mode": mode,
            "carrier_scac": scac, "origin": prev, "destination": dst,
            "depart_ts": dep, "arrive_ts": dep + timedelta(days=1),
        })
        prev = dst
    seq = ["PU"] + ["IT"] * random.randint(1, 3) + ["AR", "DP", "OD"]
    if status == "DELIVERED":
        seq += ["DL"]
    if status == "EXCEPTION":
        seq.insert(random.randint(1, len(seq)), "EX")
    for k, code in enumerate(seq):
        # timestamps are carrier-supplied and occasionally out of order
        ts = ship_dt + timedelta(days=k * transit / max(1, len(seq)))
        if random.random() < 0.04:
            ts = ts - timedelta(days=1)
        pg["tracking_event"].append({
            "shipment_id": sid, "event_seq": k + 1, "event_code": code,
            "event_description": dict(EVENTS)[code],
            "event_ts": ts,
            "event_location": random.choice(pool)[0],
        })
    charges = [("FREIGHT", money(cost * random.uniform(.65, .9)))]
    for c in ["FUEL", "RESIDENTIAL", "LIFTGATE", "DETENTION"]:
        if random.random() < (.9 if c == "FUEL" else .15):
            charges.append((c, money(cost * random.uniform(.02, .18))))
    for c, a in charges:
        pg["charge"].append({"shipment_id": sid, "charge_code": c, "amount_usd": a,
                             "currency": "USD"})

# =========================================================================
#  LOAD
# =========================================================================
import pandas as pd

SCHEMAS = {"sage_x3": x3, "hubspot": hs, "paycom": pc, "netstock": ns, "pangea": pg}

if os.path.exists(OUT_DB):
    os.remove(OUT_DB)
con = duckdb.connect(OUT_DB)

for schema, tables in SCHEMAS.items():
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    for tname, rows in tables.items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        con.register("_stg", df)
        con.execute(f'CREATE OR REPLACE TABLE {schema}."{tname}" AS SELECT * FROM _stg')
        con.unregister("_stg")

# portable DDL for moving to Postgres / SQL Server later
TYPE_MAP = {"BIGINT": "bigint", "INTEGER": "integer", "DOUBLE": "numeric(18,4)",
            "VARCHAR": "varchar(255)", "DATE": "date", "BOOLEAN": "boolean",
            "TIMESTAMP": "timestamp", "HUGEINT": "numeric(38,0)"}
cols = con.execute("""
    SELECT table_schema, table_name, column_name, data_type, ordinal_position
    FROM information_schema.columns
    WHERE table_schema IN ('sage_x3','hubspot','paycom','netstock','pangea')
    ORDER BY table_schema, table_name, ordinal_position
""").fetchall()

ddl, cur_tbl = [], None
for sch, tbl, col, dtype, _ in cols:
    if (sch, tbl) != cur_tbl:
        if cur_tbl:
            ddl.append("\n);\n")
        ddl.append(f'\nCREATE TABLE {sch}."{tbl}" (')
        cur_tbl = (sch, tbl)
        first = True
    ddl.append(("" if first else ",") + f'\n    "{col}" {TYPE_MAP.get(dtype, "varchar(255)")}')
    first = False
ddl.append("\n);\n")

with open(OUT_DDL, "w") as fh:
    fh.write("-- Portable DDL for the five mock source schemas.\n")
    for s in SCHEMAS:
        fh.write(f"CREATE SCHEMA IF NOT EXISTS {s};\n")
    fh.write("".join(ddl))

print(f"{'schema.table':<40} {'rows':>10}")
print("-" * 52)
total = 0
for sch, tables in SCHEMAS.items():
    for t in tables:
        if not tables[t]:
            continue
        n = con.execute(f'SELECT count(*) FROM {sch}."{t}"').fetchone()[0]
        total += n
        print(f"{sch + '.' + t:<40} {n:>10,}")
print("-" * 52)
print(f"{'TOTAL':<40} {total:>10,}")
con.close()
print(f"\nWrote {OUT_DB}")
