"""The synthetic source systems: one deterministic timeline, viewable as of any day.

    timeline = build_timeline()          # every event from START to TIMELINE_END
    state = state_as_of(timeline, day)   # what each system shows on that day

Three systems are generated:

    sage_x3    ERP, the highest fidelity: real X3 naming, CHAR padding, 1753
               sentinel dates, integer local menus, no enforced keys
    hubspot    CRM, shaped like its REST API: string properties, archived flags
    netstock   Demand planning, regenerated wholesale on every sync

plus a synthetic Azure cost export (`azure_cost`) so the platform can track its
own cost, and `truth`: the real identity behind every customer and employee
record, which is the answer key MDM providers are scored against. Nothing in
the pipeline reads `truth`.

Everything is simulated forward from each document's own date, so the full
timeline contains orders that ship next week and invoices paid next month.
`state_as_of` removes or rolls back every event after the given day,
consistently across the documents that reference it. That is what lets
`sources/clock.py` replay day after day and turn the differences into change
data capture rows.

Deliberate data-quality landmines are documented in docs/sources.md.
"""
from __future__ import annotations

import copy
import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

SEED = 20260905

START = date(2024, 7, 1)
#: The day the platform is first loaded. The clock starts here.
INITIAL_DATE = date(2026, 9, 5)
#: The last day the clock can advance to.
TIMELINE_END = date(2026, 10, 31)
#: Business activity is generated up to here; later days only resolve events.
END = TIMELINE_END

NULL_DATE = date(1753, 1, 1)  # X3-on-SQL-Server sentinel for "no date"

N_CUSTOMERS = 220
N_ITEMS = 420
N_SUPPLIERS = 45
N_SALES_REPS = 28
N_ORDERS = 4400
N_HS_COMPANIES = 260
N_HS_CONTACTS = 900
N_HS_DEALS = 850

EMAIL_DOMAIN = "globexdist.com"


def _stable_rng(*parts) -> random.Random:
    """An RNG keyed by its arguments, so a value depends only on what it describes."""
    key = ":".join(str(p) for p in parts)
    return random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))


@dataclass
class Timeline:
    x3: dict
    hs: dict
    ns_static: dict
    cost_static: dict
    truth: dict
    #: Hidden event dates per document, used by state_as_of. Never written out.
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Reference data shared by every system
# ---------------------------------------------------------------------------
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

# Local menus: integer enums resolved through a menu table. Verify the real
# table name against the client's folder; the mechanism is right.
LOCAL_MENUS = {
    (415, 1): "Firm", (415, 2): "Closed", (415, 3): "Cancelled",   # ORDSTA_0
    (1, 1): "No", (1, 2): "Yes",
    (20, 1): "Active", (20, 2): "Not usable", (20, 3): "Obsolete",  # ITMSTA_0
    (700, 1): "Receipt", (700, 2): "Issue", (700, 3): "Adjustment",
    (700, 4): "Transfer in", (700, 5): "Transfer out",
    (700, 6): "Customer return",
    (720, 1): "Damaged in transit", (720, 2): "Wrong item shipped",
    (720, 3): "Quality defect", (720, 4): "Over-shipment",
    (720, 5): "Customer cancelled", (720, 6): "Not specified",
    (730, 1): "Cycle count", (730, 2): "Full physical",
    (740, 1): "Open", (740, 2): "Counted", (740, 3): "Posted",
    (861, 1): "Reorder point", (861, 2): "MRP", (861, 3): "Manual",  # REOMODE_0
}

#: X3 function profiles (AUTILIS.PRFFCT_0). seeds/function_profile_department.csv
#: maps them to departments; the departments themselves are placeholders.
FUNCTION_PROFILES = {
    "SALES": 0, "CSR": 3, "BUYER": 3, "WHSE": 5, "PLANNER": 2, "AR": 2,
}

DEPARTMENT_OF_PROFILE = {
    "SALES": "SALES", "CSR": "CUSTSVC", "BUYER": "PURCH", "WHSE": "WHSE",
    "PLANNER": "PLAN", "AR": "FIN",
}

HUBSPOT_TEAMS = {"SALES": ["Field Sales - US", "Field Sales - Canada", "Inside Sales"],
                 "CSR": ["Customer Success"]}


def pad(s, n):
    """Mimic the CHAR(n) padding X3 returns from SQL Server."""
    return str(s).ljust(n)


def money(x):
    return round(float(x), 2)


def build_timeline() -> Timeline:
    """Generate every event from START to TIMELINE_END. Deterministic."""
    random.seed(SEED)
    meta: dict = {"order": {}, "item": {}, "customer": {}, "hs_company": {},
                  "hs_contact": {}, "deal": {}, "stock_moves": {}}

    def rdate(a=START, b=END):
        return a + timedelta(days=random.randint(0, (b - a).days))

    def choice_w(items, weights):
        return random.choices(items, weights=weights, k=1)[0]

    def side_rng(tag):
        return random.Random(f"{SEED}:{tag}")

    x3: dict = {}
    x3["COMPANY"] = [
        {"CPY_0": c, "CPYNAM_0": n, "CRY_0": cry, "LEG_0": leg, "CPYLOG_0": 2}
        for c, n, cry, leg in COMPANIES
    ]
    x3["FACILITY"] = [
        {"FCY_0": f, "FCYSHO_0": sho, "FCYNAM_0": n, "LEGCPY_0": cpy, "CRY_0": cry,
         "CTY_0": city, "SAT_0": st, "FCYSTO_0": 2, "FCYSAL_0": 2, "FCYPUR_0": 2}
        for f, n, cpy, sho, cry, city, st in SITES
    ]
    x3["APLSTD"] = [
        {"CHAPTER_0": ch, "CODE_0": co, "LANNUM_0": "ENG", "TEXTE_0": txt}
        for (ch, co), txt in LOCAL_MENUS.items()
    ]

    # ------------------------------------------------------------- people ----
    # Sales reps, and the X3 users who create documents. Each person has one
    # true identity in `truth`, which X3 (AUTILIS, REPRESENT) and HubSpot
    # (owner) describe differently.
    used = set()

    def person(i):
        while True:
            f, last = FIRST[i % len(FIRST)], LAST[(i * 3 + i // len(FIRST)) % len(LAST)]
            if (f, last) not in used:
                used.add((f, last))
                return f, last
            i += 7

    people = []
    for i in range(N_SALES_REPS):
        f, last = person(i)
        people.append({"entity": f"EMP{i + 1:03d}", "first": f, "last": last,
                       "profile": "SALES", "fcy": SITE_CODES[i % 3], "rep": f"REP{i + 1:03d}"})
    k = N_SALES_REPS
    for profile, n in FUNCTION_PROFILES.items():
        for _ in range(n):
            f, last = person(k)
            people.append({"entity": f"EMP{k + 1:03d}", "first": f, "last": last,
                           "profile": profile, "fcy": SITE_CODES[k % 3], "rep": None})
            k += 1
    for p in people:
        p["user"] = (p["first"][0] + p["last"]).upper()[:10]
        p["email"] = f"{p['first'].lower()}.{p['last'].lower()}@{EMAIL_DOMAIN}"

    reps = [p for p in people if p["profile"] == "SALES"]
    REP_CODES = [p["rep"] for p in reps]
    users_by_profile = {}
    for p in people:
        users_by_profile.setdefault(p["profile"], []).append(p["user"])
    rep_user = {p["rep"]: p["user"] for p in reps}

    pr = side_rng("users")
    x3["AUTILIS"] = []
    for n, p in enumerate(people):
        email = p["email"]
        if n in (5, 31):
            email = ""                     # two users never had an email recorded
        x3["AUTILIS"].append({
            "USR_0": p["user"], "NOMUSR_0": f"{p['first']} {p['last']}",
            "ADDEML_0": email, "PRFFCT_0": p["profile"], "FCY_0": p["fcy"],
            "ENAFLG_0": 2, "UPDTICK_0": pr.randint(1, 30),
        })
    for code, name in (("ADMIN", "Administrator"), ("EDI", "EDI interface"),
                       ("WMS", "Warehouse system")):
        x3["AUTILIS"].append({"USR_0": code, "NOMUSR_0": name, "ADDEML_0": "",
                              "PRFFCT_0": "SYSTEM", "FCY_0": "", "ENAFLG_0": 2,
                              "UPDTICK_0": 1})

    x3["REPRESENT"] = [{"REPNUM_0": p["rep"],
                        "REPNAM_0": f"{p['last'].upper()} {p['first'].upper()}",
                        "FCY_0": p["fcy"], "REPTYP_0": 1, "UPDTICK_0": 1} for p in reps]

    # -------------------------------------------------------------- items ----
    items = []
    for i in range(N_ITEMS):
        cat = choice_w(ITEM_CATS, CAT_WEIGHTS)
        ref = f"{cat}-{10000 + i * 7:05d}"
        des = f"{random.choice(PROD_ADJ)} {random.choice(PROD_NOUNS)} {random.choice(PROD_SIZE)}"
        sta = choice_w([1, 2, 3], [0.88, 0.05, 0.07])
        cre = rdate(date(2019, 1, 1), date(2025, 6, 1))
        items.append({"ITMREF_0": ref, "cat": cat, "des": des, "ITMSTA_0": sta,
                      "BASPRI_0": money(random.uniform(4, 900)), "CREDAT_0": cre})
    ITEM_REFS = [it["ITMREF_0"] for it in items]

    x3["ITMMASTER"] = []
    for it in items:
        base = it["BASPRI_0"]
        upd = rdate(it["CREDAT_0"], END)
        x3["ITMMASTER"].append({
            "ITMREF_0": it["ITMREF_0"], "ITMDES1_0": it["des"],
            "ITMDES2_0": "" if random.random() < 0.55 else f"Rev {random.choice('ABCD')}",
            "TCLCOD_0": it["cat"],
            "TSICOD_0": random.choice(["STD", "PRM", "ECO"]),
            "TSICOD_1": random.choice(["", "", "OEM", "AFT"]), "TSICOD_2": "",
            "STU_0": choice_w(["EA", "BOX", "KG", "M"], [0.75, 0.12, 0.08, 0.05]),
            "ITMSTA_0": it["ITMSTA_0"], "BASPRI_0": base,
            "PURBASPRI_0": money(base * random.uniform(0.42, 0.68)),
            "EANCOD_0": "" if random.random() < 0.4 else str(random.randint(10**12, 10**13 - 1)),
            "ITMWEI_0": money(random.uniform(0.05, 42)),
            "CREDAT_0": it["CREDAT_0"], "UPDDAT_0": upd,
            "CREUSR_0": random.choice(["ADMIN"] + users_by_profile["PLANNER"]),
            "UPDTICK_0": random.randint(1, 400),
        })
        # An item made obsolete on its last update date was active before it.
        meta["item"][it["ITMREF_0"]] = {"changed_on": upd, "prev_status": 1}

    x3["ITMFACILIT"] = []
    for it in items:
        for fcy in random.sample(SITE_CODES, choice_w([1, 2, 3], [0.25, 0.35, 0.40])):
            x3["ITMFACILIT"].append({
                "ITMREF_0": it["ITMREF_0"], "STOFCY_0": fcy,
                "REOMODE_0": choice_w([1, 2, 3], [0.55, 0.30, 0.15]),
                "SAFSTO_0": float(random.randint(0, 400)),
                "REOMINQTY_0": float(random.randint(0, 250)),
                "REOMAXQTY_0": float(random.randint(300, 2500)),
                "LTISUP_0": random.randint(3, 65),
                "ABCCLS_0": choice_w(["A", "B", "C"], [0.2, 0.3, 0.5]),
                "UPDTICK_0": random.randint(1, 90),
            })
    ITEM_SITE = [(r["ITMREF_0"], r["STOFCY_0"]) for r in x3["ITMFACILIT"]]

    # -------------------------------------------------- business partners ----
    customers, suppliers, used_names = [], [], set()
    for i in range(N_CUSTOMERS):
        while True:
            nm = f"{random.choice(CUST_A)} {random.choice(CUST_B)} {random.choice(CUST_C)}"
            if nm not in used_names:
                used_names.add(nm)
                break
        cn = "CA" if random.random() < 0.18 else "US"
        customers.append({"BPCNUM_0": f"C{1000 + i * 3:05d}", "name": nm, "cry": cn})
    for i in range(N_SUPPLIERS):
        nm = (f"{random.choice(CUST_A)} "
              f"{random.choice(['Metals', 'Castings', 'Polymers', 'Import', 'Forge', 'Trading'])} "
              f"{random.choice(CUST_C)}")
        suppliers.append({"BPSNUM_0": f"S{2000 + i * 3:05d}", "name": nm,
                          "lt": random.randint(7, 90)})

    x3["BPARTNER"] = []
    for c in customers:
        x3["BPARTNER"].append({"BPRNUM_0": c["BPCNUM_0"], "BPRNAM_0": c["name"], "BPRNAM_1": "",
                               "BPCFLG_0": 2, "BPSFLG_0": 1,
                               "CRY_0": "USA" if c["cry"] == "US" else "CAN",
                               "CUR_0": "USD" if c["cry"] == "US" else "CAD",
                               "BPRLOG_0": 1, "UPDTICK_0": random.randint(1, 50)})
    for s in suppliers:
        x3["BPARTNER"].append({"BPRNUM_0": s["BPSNUM_0"], "BPRNAM_0": s["name"], "BPRNAM_1": "",
                               "BPCFLG_0": 1, "BPSFLG_0": 2, "CRY_0": "USA",
                               "CUR_0": "USD", "BPRLOG_0": 1,
                               "UPDTICK_0": random.randint(1, 50)})

    x3["BPCUSTOMER"] = []
    for c in customers:
        cre = rdate(date(2018, 1, 1), date(2024, 6, 1))
        upd = rdate(cre, END)
        r1 = random.choice(REP_CODES)
        x3["BPCUSTOMER"].append({
            "BPCNUM_0": c["BPCNUM_0"], "BPCNAM_0": c["name"],
            "BPCGRU_0": choice_w(["NATL", "REGL", "DIST", "OEM"], [.2, .4, .25, .15]),
            "CUR_0": "USD" if c["cry"] == "US" else "CAD",
            "PTE_0": choice_w(["NET30", "NET45", "NET60", "COD"], [.55, .2, .15, .10]),
            "BPCSNC_0": float(random.choice([0, 25000, 50000, 100000, 250000])),
            "OSTCTL_0": choice_w([1, 2], [.85, .15]), "ACCCOD_0": "CUS",
            "REP_0": r1,
            "REP_1": random.choice(REP_CODES) if random.random() < 0.18 else "",
            "CREDAT_0": cre, "UPDDAT_0": upd, "UPDTICK_0": random.randint(1, 120),
        })
        # The last update reassigned the account: before it, another rep had it.
        # This is the as-was attribution case (open question 11).
        meta["customer"][c["BPCNUM_0"]] = {"changed_on": upd,
                                           "prev_rep": random.choice(REP_CODES)}

    x3["BPSUPPLIER"] = [{"BPSNUM_0": s["BPSNUM_0"], "BPSNAM_0": s["name"], "CUR_0": "USD",
                         "PTE_0": random.choice(["NET30", "NET45"]), "LTI_0": s["lt"],
                         "ACCCOD_0": "SUP", "UPDTICK_0": random.randint(1, 60)}
                        for s in suppliers]

    x3["BPADDRESS"] = []
    for c in customers:
        pool = US_CITIES if c["cry"] == "US" else CA_CITIES
        for k in range(choice_w([1, 2, 3], [.6, .3, .1])):
            city, st, zp = random.choice(pool)
            x3["BPADDRESS"].append({
                "BPATYP_0": 1, "BPANUM_0": c["BPCNUM_0"],
                "BPAADD_0": "MAIN" if k == 0 else f"SHIP{k}",
                "BPADES_0": "Head Office" if k == 0 else "Ship To",
                "ADDLIG_0": f"{random.randint(100, 9800)} "
                            f"{random.choice(['Industrial', 'Commerce', 'Enterprise', 'Ridge', 'Foundry'])} "
                            f"{random.choice(['Blvd', 'Dr', 'Pkwy', 'Rd'])}",
                "ADDLIG_1": "" if random.random() < .8 else f"Suite {random.randint(100, 900)}",
                "CTY_0": city, "SAT_0": st, "POSCOD_0": zp,
                "CRY_0": "USA" if c["cry"] == "US" else "CAN",
                "TEL_0": f"({random.randint(200, 989)}) {random.randint(200, 999)}-"
                         f"{random.randint(1000, 9999)}",
            })

    # ------------------------------------------------------- sales orders ----
    PRICE_BY_ITEM = {m["ITMREF_0"]: m["BASPRI_0"] for m in x3["ITMMASTER"]}
    ITEM_DES = {m["ITMREF_0"]: m["ITMDES1_0"] for m in x3["ITMMASTER"]}
    ITEMS_BY_SITE = {}
    for itm, fcy in ITEM_SITE:
        ITEMS_BY_SITE.setdefault(fcy, []).append(itm)

    def seasonal_weight(d):
        return 1.0 + 0.35 * math.sin((d.month - 3) / 12 * 2 * math.pi) + 0.0006 * (d - START).days

    order_dates, cur = [], START
    while cur <= END:
        if cur.weekday() < 5:
            order_dates.append(cur)
        cur += timedelta(days=1)
    date_weights = [seasonal_weight(d) for d in order_dates]

    x3["SORDER"], x3["SORDERQ"], x3["SORDERP"] = [], [], []
    order_index, order_lines = {}, []
    for i in range(N_ORDERS):
        d = random.choices(order_dates, weights=date_weights, k=1)[0]
        cust = random.choice(customers)
        fcy = "CA001" if cust["cry"] == "CA" else random.choice(["US001", "US002"])
        soh = f"SO{fcy[:2]}{d.year % 100:02d}{i:06d}"
        fate = choice_w(["ship", "cancel", "backorder"], [.93, .04, .03])
        shidat = d + timedelta(days=random.randint(1, 21)) if fate == "ship" else NULL_DATE
        cancel_on = d + timedelta(days=random.randint(1, 10)) if fate == "cancel" else None
        # A quarter of cancelled orders are hard-deleted two weeks later. X3
        # allows it, and only change data capture sees the delete.
        delete_on = (cancel_on + timedelta(days=14)
                     if cancel_on and random.random() < 0.25 else None)
        rep = random.choice(REP_CODES)
        creator = choice_w([rep_user[rep], random.choice(users_by_profile["CSR"]), "EDI"],
                           [.75, .15, .10])
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
                "DEMDLVDAT_0": d + timedelta(days=random.randint(4, 40)),
                "SHTQTY_0": 0.0, "UOM_0": "EA", "UPDTICK_0": random.randint(1, 20),
            })
            x3["SORDERP"].append({
                "SOHNUM_0": soh, "SOPLIN_0": lineno, "SOPSEQ_0": 1,
                "ITMREF_0": pad(itm, 20), "ITMDES1_0": ITEM_DES.get(itm, ""),
                "GROPRI_0": gross, "NETPRI_0": net, "DISCRGVAL1_0": disc,
                "AMTNOTLIN_0": line_amt, "VAT1_0": "STD", "UPDTICK_0": random.randint(1, 20),
            })
            order_lines.append((soh, lineno, itm, qty, net, d, fcy))
        x3["SORDER"].append({
            "SOHNUM_0": soh, "SALFCY_0": fcy, "STOFCY_0": fcy,
            "BPCORD_0": pad(cust["BPCNUM_0"], 15),   # CHAR-padded on purpose
            "BPCINV_0": cust["BPCNUM_0"],
            "ORDDAT_0": d, "SHIDAT_0": shidat,
            "CUR_0": "CAD" if cust["cry"] == "CA" else "USD",
            "ORDSTA_0": 2 if fate == "ship" else (3 if fate == "cancel" else 1),
            "REP_0": rep, "REP_1": "", "TOTLINAMT_0": money(total),
            "ORDINVSTA_0": 1, "CREUSR_0": creator, "CREDAT_0": d, "UPDDAT_0": d,
            "UPDTICK_0": random.randint(1, 40),
        })
        order_index[soh] = {"cust": cust, "date": d, "fcy": fcy, "shidat": shidat,
                            "shipped": fate == "ship", "total": money(total), "rep": rep}
        meta["order"][soh] = {"date": d, "shidat": shidat, "cancel_on": cancel_on,
                              "delete_on": delete_on, "invoiced_on": None}

    lines_by_order = {}
    for (soh, lineno, itm, qty, net, _d, _fcy) in order_lines:
        lines_by_order.setdefault(soh, []).append((lineno, itm, qty, net))

    # -------------------------------------------------------- deliveries -----
    # One delivery per shipped order; 6% ship short and send the balance on a
    # second delivery. DLVDAT_0 is the proof-of-delivery date, which arrives
    # after the goods do.
    dr = side_rng("deliveries")
    x3["SDELIVERY"], x3["SDELIVERYD"] = [], []
    sdh_seq = 0
    for soh in sorted(order_index):
        h = order_index[soh]
        if not h["shipped"]:
            continue
        split = dr.random() < 0.06
        waves = [h["shidat"]]
        if split:
            waves.append(h["shidat"] + timedelta(days=dr.randint(3, 15)))
        for wave_no, ship_on in enumerate(waves):
            sdh_seq += 1
            sdh = f"SDH{h['fcy'][:2]}{ship_on.year % 100:02d}{sdh_seq:06d}"
            transit = dr.choices([1, 2, 3, 4, 5, 7, 9], [.15, .25, .2, .15, .1, .1, .05])[0]
            x3["SDELIVERY"].append({
                "SDHNUM_0": sdh, "STOFCY_0": h["fcy"], "SALFCY_0": h["fcy"],
                "BPCORD_0": pad(h["cust"]["BPCNUM_0"], 15), "SOHNUM_0": soh,
                "SHIDAT_0": ship_on, "DLVDAT_0": ship_on + timedelta(days=transit),
                "CFMFLG_0": 2, "CREUSR_0": dr.choice(users_by_profile["WHSE"] + ["WMS"]),
                "UPDTICK_0": dr.randint(1, 8),
            })
            for k, (lineno, itm, qty, net) in enumerate(lines_by_order[soh]):
                first_wave = float(max(1, round(qty * 0.6))) if split else qty
                dq = first_wave if wave_no == 0 else qty - first_wave
                if dq <= 0:
                    continue
                x3["SDELIVERYD"].append({
                    "SDHNUM_0": sdh, "SDDLIN_0": (k + 1) * 1000, "SOHNUM_0": soh,
                    "SOPLIN_0": lineno, "ITMREF_0": pad(itm, 20), "STOFCY_0": h["fcy"],
                    "QTY_0": float(dq), "NETPRI_0": net,
                })

    # ---------------------------------------------------------- invoices -----
    x3["SINVOICEV"], x3["SINVOICED"] = [], []
    inv_seq, inv_by_order = 0, {}
    for soh, h in order_index.items():
        if not h["shipped"] or random.random() < 0.06:      # some shipped orders uninvoiced
            continue
        inv_seq += 1
        num = f"SI{h['fcy'][:2]}{h['date'].year % 100:02d}{inv_seq:06d}"
        invdat = h["shidat"] + timedelta(days=random.randint(0, 6))
        meta["order"][soh]["invoiced_on"] = invdat
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
        inv_by_order[soh] = (num, invdat)
        tax = money(tot * (0.0825 if h["fcy"].startswith("US") else 0.13))
        x3["SINVOICEV"].append({
            "NUM_0": num, "SIVTYP_0": "SIN", "INVDAT_0": invdat,
            "BPR_0": h["cust"]["BPCNUM_0"], "SALFCY_0": h["fcy"],
            "CUR_0": "CAD" if h["cust"]["cry"] == "CA" else "USD",
            "AMTNOTLIN_0": money(tot), "AMTTAXLIN_0": tax, "AMTATILIN_0": money(tot + tax),
            "INVSTA_0": choice_w([1, 2], [.12, .88]),
            "PAYDAT_0": invdat + timedelta(days=random.choice([28, 30, 31, 45, 47, 62, 90]))
            if random.random() < 0.86 else NULL_DATE,
            "ACCDAT_0": invdat, "UPDTICK_0": random.randint(1, 15),
        })

    # ---------------------------------------------------- stock + journal ----
    x3["STOCK"] = []
    seen_positions = set()
    for itm, fcy in ITEM_SITE:
        for _ in range(choice_w([1, 2, 3], [.6, .3, .1])):
            lot = f"L{random.randint(100000, 999999)}"
            loc = f"{random.choice('ABCDE')}{random.randint(1, 24):02d}-{random.randint(1, 6)}"
            if (fcy, itm, lot, loc) in seen_positions:
                continue
            seen_positions.add((fcy, itm, lot, loc))
            x3["STOCK"].append({
                "STOFCY_0": fcy, "ITMREF_0": itm, "LOT_0": lot, "LOC_0": loc,
                "QTYSTU_0": float(random.randint(0, 3000)),
                "STA_0": choice_w(["A", "Q", "R"], [.92, .05, .03]),
                "OWNER_0": fcy, "UPDTICK_0": random.randint(1, 200),
            })

    x3["STOJOU"] = []
    rowid = 0
    for sd in x3["SDELIVERYD"]:
        rowid += 1
        hdr_date = None
        x3["STOJOU"].append({
            "ROWID": rowid, "ITMREF_0": sd["ITMREF_0"], "STOFCY_0": sd["STOFCY_0"],
            "IPTDAT_0": hdr_date, "TRSTYP_0": 2, "QTYSTU_0": -sd["QTY_0"],
            "VCRNUM_0": sd["SDHNUM_0"], "VCRTYP_0": "SDH",
            "LOT_0": f"L{random.randint(100000, 999999)}", "CREUSR_0": "WMS", "UPDTICK_0": 1,
        })
    ship_dates = {h["SDHNUM_0"]: h["SHIDAT_0"] for h in x3["SDELIVERY"]}
    for mv in x3["STOJOU"]:
        mv["IPTDAT_0"] = ship_dates[mv["VCRNUM_0"]]
    for _ in range(6000):
        itm, fcy = random.choice(ITEM_SITE)
        t = choice_w([1, 3, 4, 5], [.72, .16, .06, .06])
        q = float(random.randint(10, 1200)) * (1 if t in (1, 4) else random.choice([1, -1]))
        when = rdate()
        lot = f"L{random.randint(100000, 999999)}"
        usr = random.choice(["WMS", "ADMIN"] + users_by_profile["WHSE"])
        if t in (4, 5):
            rowid += 1
            x3["STOJOU"].append({
                "ROWID": rowid, "ITMREF_0": pad(itm, 20), "STOFCY_0": fcy,
                "IPTDAT_0": when, "TRSTYP_0": t, "QTYSTU_0": q,
                "VCRNUM_0": f"TRF{random.randint(100000, 999999)}", "VCRTYP_0": "TRF",
                "LOT_0": lot, "CREUSR_0": usr, "UPDTICK_0": 1,
            })

    # --------------------------------------------------- purchase orders -----
    x3["PORDER"], x3["PORDERQ"] = [], []
    for i in range(1500):
        d = rdate()
        s = random.choice(suppliers)
        fcy = random.choice(SITE_CODES)
        poh = f"PO{fcy[:2]}{d.year % 100:02d}{i:06d}"
        x3["PORDER"].append({
            "POHNUM_0": poh, "POHFCY_0": fcy, "BPSNUM_0": s["BPSNUM_0"],
            "ORDDAT_0": d, "ORDSTA_0": choice_w([1, 2, 3], [.2, .75, .05]),
            "CUR_0": "USD", "CREUSR_0": random.choice(users_by_profile["BUYER"] + ["ADMIN"]),
            "UPDTICK_0": random.randint(1, 20),
        })
        for ln in range(choice_w([1, 2, 3, 6], [.4, .3, .2, .1])):
            itm = random.choice(ITEM_REFS)
            q = float(random.randint(50, 2000))
            exp = d + timedelta(days=s["lt"] + random.randint(-5, 30))
            rcp = q * choice_w([1.0, 0.0, 0.85], [.7, .2, .1])
            x3["PORDERQ"].append({
                "POHNUM_0": poh, "POPLIN_0": (ln + 1) * 1000, "POQSEQ_0": 1,
                "ITMREF_0": itm, "POHFCY_0": fcy, "QTYUOM_0": q, "EXTRCPDAT_0": exp,
                "RCPQTY_0": rcp,
                "RCPDAT_0": exp + timedelta(days=random.randint(-3, 18)) if rcp > 0 else NULL_DATE,
                "NETPRI_0": money(PRICE_BY_ITEM.get(itm, 50) * random.uniform(.4, .65)),
                "UPDTICK_0": random.randint(1, 20),
            })

    # ---------------------------------------------------------------- GL -----
    x3["GACCENTRY"], x3["GACCENTRYD"] = [], []
    gnum = 0

    def post(num_src, typ, jou, fcy, accdat, cur, des, bpr, rows):
        nonlocal gnum
        gnum += 1
        gl = f"GL{gnum:08d}"
        cpy = "GLBCA" if fcy == "CA001" else "GLBUS"
        x3["GACCENTRY"].append({
            "NUM_0": gl, "TYP_0": typ, "JOU_0": jou, "CPY_0": cpy, "FCY_0": fcy,
            "ACCDAT_0": accdat, "CUR_0": cur, "DES_0": des, "VCRNUM_0": num_src,
            "STA_0": 3, "UPDTICK_0": 1,
        })
        for k, (acc, sns, amt) in enumerate(rows):
            x3["GACCENTRYD"].append({
                "NUM_0": gl, "LIN_0": (k + 1) * 1000, "ACC_0": acc, "SNS_0": sns,
                "AMTCUR_0": money(amt), "AMTLOC_0": money(amt * (0.74 if cur == "CAD" else 1.0)),
                "BPR_0": bpr, "CPY_0": cpy, "FCY_0": fcy, "DSP_0": "", "ACCDAT_0": accdat,
            })

    for v in x3["SINVOICEV"]:
        post(v["NUM_0"], "SIH", "SAL", v["SALFCY_0"], v["ACCDAT_0"], v["CUR_0"],
             f"Invoice {v['NUM_0']}", v["BPR_0"],
             [("11100", 1, v["AMTATILIN_0"]), ("41000", -1, v["AMTNOTLIN_0"]),
              ("22300", -1, v["AMTTAXLIN_0"])])

    # ------------------------------------------------------ sales returns ----
    rr = side_rng("returns")
    x3["SRETURN"], x3["SRETURND"] = [], []
    rtn_seq, return_moves, credit_memos = 0, [], []
    for soh in sorted(inv_by_order):
        if not lines_by_order.get(soh) or rr.random() >= 0.035:
            continue
        h = order_index[soh]
        inv_num, invdat = inv_by_order[soh]
        rtn_seq += 1
        fcy = h["fcy"]
        srh = f"RTN{fcy[:2]}{invdat.year % 100:02d}{rtn_seq:05d}"
        rtndat = invdat + timedelta(days=rr.randint(5, 75))
        # 8% arrive with an order reference nobody can resolve. Land them.
        ref_soh, r = soh, rr.random()
        if r < 0.05:
            ref_soh = ""
        elif r < 0.08:
            ref_soh = soh.lower()
        x3["SRETURN"].append({
            "SRHNUM_0": srh, "SRHFCY_0": fcy, "BPCNUM_0": h["cust"]["BPCNUM_0"],
            "RTNDAT_0": rtndat, "SOHNUM_0": ref_soh, "SIVNUM_0": inv_num,
            "RTNSTA_0": rr.choices([1, 2, 3], [.06, .10, .84])[0],
            "RTNREN_0": rr.choices([1, 2, 3, 4, 5, 6], [.28, .19, .24, .09, .12, .08])[0],
            "CREUSR_0": rr.choice(users_by_profile["CSR"]),
            "UPDTICK_0": rr.randint(1, 12),
        })
        picked = rr.sample(lines_by_order[soh],
                           k=min(len(lines_by_order[soh]), rr.choices([1, 2], [.78, .22])[0]))
        rtn_total, credited = 0.0, []
        for k, (lineno, itm, qty, net) in enumerate(picked):
            rqty = float(max(1, int(qty * rr.choice([0.25, 0.5, 1.0, 1.0]))))
            amt = money(net * rqty)
            rtn_total += amt
            credited.append((lineno, itm, rqty, net, amt))
            x3["SRETURND"].append({
                "SRHNUM_0": srh, "SRDLIN_0": (k + 1) * 1000, "ITMREF_0": itm,
                "QTY_0": rqty, "NETPRI_0": net, "AMTNOTLIN_0": amt,
                "SOHNUM_0": ref_soh, "SOPLIN_0": lineno, "STOFCY_0": fcy,
                "RTNREN_0": rr.choices([1, 2, 3, 4, 5, 6], [.28, .19, .24, .09, .12, .08])[0],
            })
            return_moves.append((itm, fcy, rtndat, rqty, srh))
        if rtn_total > 0 and rr.random() < 0.86:      # 14% not yet credited
            credit_memos.append((srh, h, rtndat, rtn_total, credited, fcy))

    memo_by_return = {}
    for (srh, h, rtndat, rtn_total, credited, fcy) in credit_memos:
        inv_seq += 1
        num = f"SC{fcy[:2]}{rtndat.year % 100:02d}{inv_seq:06d}"
        memo_by_return[srh] = num
        for k, (lineno, itm, rqty, net, amt) in enumerate(credited):
            x3["SINVOICED"].append({
                "NUM_0": num, "SIDLIN_0": (k + 1) * 1000, "ITMREF_0": itm,
                "ITMDES1_0": "", "QTY_0": -rqty, "NETPRI_0": net,
                "AMTNOTLIN_0": money(-amt), "SOHNUM_0": "", "SOPLIN_0": lineno,
                "STOFCY_0": fcy,
            })
        cur = "CAD" if h["cust"]["cry"] == "CA" else "USD"
        tax = money(-rtn_total * (0.0825 if fcy.startswith("US") else 0.13))
        x3["SINVOICEV"].append({
            "NUM_0": num, "SIVTYP_0": "SCR", "INVDAT_0": rtndat,
            "BPR_0": h["cust"]["BPCNUM_0"], "SALFCY_0": fcy, "CUR_0": cur,
            "AMTNOTLIN_0": money(-rtn_total), "AMTTAXLIN_0": tax,
            "AMTATILIN_0": money(-rtn_total + tax), "INVSTA_0": 2,
            "PAYDAT_0": rtndat + timedelta(days=rr.choice([21, 30, 45]))
            if rr.random() < 0.80 else NULL_DATE,
            "ACCDAT_0": rtndat, "UPDTICK_0": rr.randint(1, 8),
        })
        # Credit memos post with the sign reversed, so revenue still reconciles.
        post(num, "SCH", "SAL", fcy, rtndat, cur, f"Credit memo {num}", h["cust"]["BPCNUM_0"],
             [("11100", 1, money(-rtn_total + tax)), ("41000", -1, money(-rtn_total)),
              ("22300", -1, tax)])

    for (itm, fcy, rtndat, rqty, srh) in return_moves:
        rowid += 1
        x3["STOJOU"].append({
            "ROWID": rowid, "ITMREF_0": pad(itm, 20), "STOFCY_0": fcy,
            "IPTDAT_0": rtndat, "TRSTYP_0": 6, "QTYSTU_0": rqty,
            "VCRNUM_0": srh, "VCRTYP_0": "SRH",
            "LOT_0": f"L{rr.randint(100000, 999999)}", "CREUSR_0": "WMS", "UPDTICK_0": 1,
        })

    # -------------------------------------- goods receipts + AP invoices -----
    pr = side_rng("purchasing")
    x3["PRECEIPT"], x3["PRECEIPTD"] = [], []
    x3["PINVOICE"], x3["PINVOICED"] = [], []
    po_index = {h["POHNUM_0"]: h for h in x3["PORDER"]}
    lines_by_po = {}
    for ln in x3["PORDERQ"]:
        lines_by_po.setdefault(ln["POHNUM_0"], []).append(ln)

    rcp_seq, rcpt_lines, receipt_moves, balance_parent = 0, {}, [], {}
    for poh in sorted(lines_by_po):
        head = po_index[poh]
        received = [ln for ln in lines_by_po[poh] if ln["RCPQTY_0"] and ln["RCPDAT_0"] != NULL_DATE]
        if not received:
            continue
        received.sort(key=lambda ln: ln["RCPDAT_0"])
        n_waves = min(len(received), pr.choices([1, 2, 3], [.72, .22, .06])[0])
        for wave in [received[i::n_waves] for i in range(n_waves)]:
            if not wave:
                continue
            rdat = max(ln["RCPDAT_0"] for ln in wave)
            rcp_seq += 1
            pth = f"PTH{head['POHFCY_0'][:2]}{rdat.year % 100:02d}{rcp_seq:06d}"
            rcpt_lines[pth] = 0
            x3["PRECEIPT"].append({
                "PTHNUM_0": pth, "PTHFCY_0": head["POHFCY_0"], "BPSNUM_0": head["BPSNUM_0"],
                "POHNUM_0": poh, "RCPDAT_0": rdat, "PTHTYP_0": 1,
                "CREUSR_0": pr.choice(users_by_profile["WHSE"]), "UPDTICK_0": pr.randint(1, 10),
            })
            for ln in wave:
                # 12% arrive short and are completed on a later receipt.
                qty = float(ln["RCPQTY_0"])
                if pr.random() < 0.12:
                    qty = money(qty * 0.6)
                rcpt_lines[pth] += 1
                x3["PRECEIPTD"].append({
                    "PTHNUM_0": pth, "PTDLIN_0": rcpt_lines[pth] * 1000, "POHNUM_0": poh,
                    "POPLIN_0": ln["POPLIN_0"], "ITMREF_0": ln["ITMREF_0"],
                    "PTHFCY_0": head["POHFCY_0"], "QTYUOM_0": money(qty), "RCPDAT_0": rdat,
                })
                receipt_moves.append((ln["ITMREF_0"], head["POHFCY_0"], rdat, qty, pth))
                if qty < float(ln["RCPQTY_0"]):
                    bal = money(float(ln["RCPQTY_0"]) - qty)
                    bdat = rdat + timedelta(days=pr.randint(5, 25))
                    rcp_seq += 1
                    bpth = f"PTH{head['POHFCY_0'][:2]}{bdat.year % 100:02d}{rcp_seq:06d}"
                    balance_parent[bpth] = pth
                    x3["PRECEIPT"].append({
                        "PTHNUM_0": bpth, "PTHFCY_0": head["POHFCY_0"],
                        "BPSNUM_0": head["BPSNUM_0"], "POHNUM_0": poh, "RCPDAT_0": bdat,
                        "PTHTYP_0": 1, "CREUSR_0": pr.choice(users_by_profile["WHSE"]),
                        "UPDTICK_0": pr.randint(1, 10),
                    })
                    x3["PRECEIPTD"].append({
                        "PTHNUM_0": bpth, "PTDLIN_0": 1000, "POHNUM_0": poh,
                        "POPLIN_0": ln["POPLIN_0"], "ITMREF_0": ln["ITMREF_0"],
                        "PTHFCY_0": head["POHFCY_0"], "QTYUOM_0": bal, "RCPDAT_0": bdat,
                    })
                    receipt_moves.append((ln["ITMREF_0"], head["POHFCY_0"], bdat, bal, bpth))

    for (itm, fcy, rdat, qty, pth) in receipt_moves:
        rowid += 1
        x3["STOJOU"].append({
            "ROWID": rowid, "ITMREF_0": pad(itm, 20), "STOFCY_0": fcy,
            "IPTDAT_0": rdat, "TRSTYP_0": 1, "QTYSTU_0": money(qty),
            "VCRNUM_0": pth, "VCRTYP_0": "PTH",
            "LOT_0": f"L{pr.randint(100000, 999999)}", "CREUSR_0": "WMS", "UPDTICK_0": 1,
        })

    # Supplier invoices. A match rate of 100% makes the metric useless and 0%
    # looks like a bug, so the failure mix is deliberate.
    rlines_by_po, rcpdat_by_po = {}, {}
    for d in x3["PRECEIPTD"]:
        rlines_by_po.setdefault(d["POHNUM_0"], []).append(d)
        rcpdat_by_po[d["POHNUM_0"]] = max(rcpdat_by_po.get(d["POHNUM_0"], d["RCPDAT_0"]),
                                          d["RCPDAT_0"])
    pinv_seq, pinv_sources = 0, {}
    for poh in sorted(rlines_by_po):
        if pr.random() >= 0.92:                       # 8% received, not yet invoiced
            continue
        head = po_index[poh]
        fcy = head["POHFCY_0"]
        invdat = rcpdat_by_po[poh] + timedelta(days=pr.randint(2, 40))
        pinv_seq += 1
        num = f"PI{fcy[:2]}{invdat.year % 100:02d}{pinv_seq:06d}"
        po_lines = {ln["POPLIN_0"]: ln for ln in lines_by_po[poh]}
        tot, k = 0.0, 0
        for rl in rlines_by_po[poh]:
            pol = po_lines.get(rl["POPLIN_0"])
            if pol is None:
                continue
            k += 1
            qty, price = float(rl["QTYUOM_0"]), float(pol["NETPRI_0"])
            pth_ref = rl["PTHNUM_0"]
            mode = pr.choices(["clean", "qty", "price", "no_receipt"], [.72, .12, .11, .05])[0]
            if mode == "qty":
                qty = money(qty * pr.choice([0.82, 0.9, 1.08, 1.2]))
            elif mode == "price":
                price = money(price * pr.choice([0.88, 0.95, 1.06, 1.15]))
            elif mode == "no_receipt":
                pth_ref = ""                          # billed, never received
            amt = money(qty * price)
            tot += amt
            pinv_sources.setdefault(num, set()).add(rl["PTHNUM_0"])
            x3["PINVOICED"].append({
                "NUM_0": num, "PIDLIN_0": k * 1000, "POHNUM_0": poh,
                "POPLIN_0": rl["POPLIN_0"], "PTHNUM_0": pth_ref, "ITMREF_0": rl["ITMREF_0"],
                "QTY_0": qty, "NETPRI_0": price, "AMTNOTLIN_0": amt, "PIHFCY_0": fcy,
            })
        if not k:
            continue
        tax = money(tot * 0.0825)
        x3["PINVOICE"].append({
            "NUM_0": num, "PIVTYP_0": "PIN", "BPSNUM_0": head["BPSNUM_0"],
            "BPSINV_0": f"{pr.randint(10000, 99999)}-{pr.randint(1, 9)}",
            "INVDAT_0": invdat, "ACCDAT_0": invdat, "PIHFCY_0": fcy, "CUR_0": "USD",
            "AMTNOTLIN_0": money(tot), "AMTTAXLIN_0": tax, "AMTATILIN_0": money(tot + tax),
            "INVSTA_0": pr.choices([1, 2], [.14, .86])[0], "UPDTICK_0": pr.randint(1, 12),
        })

    # Maverick spend: invoices with no purchase order at all, about 3% of AP.
    for _ in range(int(len(x3["PINVOICE"]) * 0.03)):
        pinv_seq += 1
        sup = suppliers[pr.randrange(len(suppliers))]
        fcy = SITE_CODES[pr.randrange(len(SITE_CODES))]
        invdat = START + timedelta(days=pr.randint(0, (END - START).days))
        num = f"PI{fcy[:2]}{invdat.year % 100:02d}{pinv_seq:06d}"
        tot = 0.0
        for k in range(pr.choices([1, 2, 3], [.6, .3, .1])[0]):
            itm = ITEM_REFS[pr.randrange(len(ITEM_REFS))]
            qty = float(pr.randint(5, 300))
            price = money(PRICE_BY_ITEM.get(itm, 50) * pr.uniform(.4, .7))
            amt = money(qty * price)
            tot += amt
            x3["PINVOICED"].append({
                "NUM_0": num, "PIDLIN_0": (k + 1) * 1000, "POHNUM_0": "", "POPLIN_0": 0,
                "PTHNUM_0": "", "ITMREF_0": itm, "QTY_0": qty, "NETPRI_0": price,
                "AMTNOTLIN_0": amt, "PIHFCY_0": fcy,
            })
        tax = money(tot * 0.0825)
        x3["PINVOICE"].append({
            "NUM_0": num, "PIVTYP_0": "PIN", "BPSNUM_0": sup["BPSNUM_0"],
            "BPSINV_0": f"{pr.randint(10000, 99999)}-{pr.randint(1, 9)}",
            "INVDAT_0": invdat, "ACCDAT_0": invdat, "PIHFCY_0": fcy, "CUR_0": "USD",
            "AMTNOTLIN_0": money(tot), "AMTTAXLIN_0": tax, "AMTATILIN_0": money(tot + tax),
            "INVSTA_0": 2, "UPDTICK_0": pr.randint(1, 12),
        })

    for v in x3["PINVOICE"]:
        post(v["NUM_0"], "PIH", "PUR", v["PIHFCY_0"], v["ACCDAT_0"], v["CUR_0"],
             f"Supplier invoice {v['NUM_0']}", v["BPSNUM_0"],
             [("21000", -1, v["AMTATILIN_0"]), ("50000", 1, v["AMTNOTLIN_0"]),
              ("22300", 1, v["AMTTAXLIN_0"])])

    # ------------------------------------------------------- cycle counts ----
    # A count session records what was counted, not only what changed: that is
    # where Inventory Accuracy's denominator comes from. A session is counted
    # on its date and posted three days later.
    cc = side_rng("counts")
    x3["STOCOUNT"], x3["STOCOUNTD"] = [], []
    ses_seq, stock_by_site = 0, {}
    for r in x3["STOCK"]:
        stock_by_site.setdefault(r["STOFCY_0"], []).append(r)
    m = date(START.year, START.month, 1)
    while m < END:
        for fcy in SITE_CODES:
            positions = stock_by_site.get(fcy, [])
            if not positions:
                continue
            ses_seq += 1
            cntdat = m + timedelta(days=cc.randint(8, 24))
            ses = f"CNT{fcy[:2]}{cntdat.year % 100:02d}{ses_seq:05d}"
            picked = cc.sample(positions, k=min(len(positions), cc.randint(28, 46)))
            x3["STOCOUNT"].append({
                "SESNUM_0": ses, "STOFCY_0": fcy, "CNTDAT_0": cntdat,
                "CNTTYP_0": 2 if m.month == 12 else 1, "SESSTA_0": 3,
                "CREUSR_0": cc.choice(users_by_profile["WHSE"]), "UPDTICK_0": cc.randint(1, 6),
            })
            for k, pos in enumerate(picked):
                theo = float(pos["QTYSTU_0"])
                if cc.random() < 0.93:
                    counted = theo
                else:
                    drift = cc.choices([0.02, 0.05, 0.12, 0.40], [.45, .30, .18, .07])[0]
                    counted = max(0.0, float(round(theo * (1 + drift * cc.choice([1, -1])))))
                x3["STOCOUNTD"].append({
                    "SESNUM_0": ses, "CNTLIN_0": (k + 1) * 1000, "ITMREF_0": pos["ITMREF_0"],
                    "STOFCY_0": fcy, "LOC_0": pos["LOC_0"], "LOT_0": pos["LOT_0"],
                    "QTYTHEO_0": theo, "QTYCNT_0": counted, "CNTSTA_0": 3,
                })
                if counted != theo:
                    rowid += 1
                    x3["STOJOU"].append({
                        "ROWID": rowid, "ITMREF_0": pad(pos["ITMREF_0"], 20), "STOFCY_0": fcy,
                        "IPTDAT_0": cntdat + timedelta(days=3), "TRSTYP_0": 3,
                        "QTYSTU_0": money(counted - theo), "VCRNUM_0": ses, "VCRTYP_0": "ADJ",
                        "LOT_0": pos["LOT_0"], "CREUSR_0": "WMS", "UPDTICK_0": 1,
                    })
        m = date(m.year + (m.month // 12), m.month % 12 + 1, 1)

    x3["ATEXTRA"] = []
    for mm in random.sample(x3["ITMMASTER"], 120):
        x3["ATEXTRA"].append({"CODFIC_0": "ITMMASTER", "ZONE_0": "DES1AXX", "LANNUM_0": "FRA",
                              "IDENT1_0": mm["ITMREF_0"], "IDENT2_0": "",
                              "TEXTE_0": "Piece " + mm["ITMDES1_0"].lower()})
    for (ch, co), txt in LOCAL_MENUS.items():
        x3["ATEXTRA"].append({"CODFIC_0": "APLSTD", "ZONE_0": "LNGDES", "LANNUM_0": "FRA",
                              "IDENT1_0": str(ch), "IDENT2_0": str(co), "TEXTE_0": txt + " (FR)"})

    # ============================================================= HUBSPOT ===
    hs: dict = {}
    hr = side_rng("hubspot-owners")
    owner_people = reps[:22] + [p for p in people if p["profile"] == "CSR"][:2]
    hs["owner"] = []
    for i, p in enumerate(owner_people):
        email = p["email"]
        if i == 3:
            email = email.title()                  # casing drift: needs normalising
        team = hr.choice(HUBSPOT_TEAMS[p["profile"]])
        hs["owner"].append({"id": str(90000000 + i * 137), "email": email,
                            "first_name": p["first"], "last_name": p["last"],
                            "user_id": str(40000 + i), "team_name": team, "archived": False,
                            "created_at": date(2023, 1, 15), "updated_at": date(2024, 2, 1)})
    OWNER_IDS = [o["id"] for o in hs["owner"]][:22]

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

    # About 78% of HubSpot companies are real X3 customers, matched by NAME only.
    hs_companies, truth_customer = [], []
    for c in customers:
        truth_customer.append({"source_system": "sage_x3", "source_key": c["BPCNUM_0"],
                               "entity_id": c["BPCNUM_0"]})
    matched = random.sample(customers, int(N_HS_COMPANIES * 0.78))
    for i in range(N_HS_COMPANIES):
        cid = str(11000000000 + i * 991)
        if i < len(matched):
            src = matched[i]
            nm = src["name"]
            r = random.random()
            if r < 0.22:
                nm = nm.replace(" Inc", ", Inc.").replace(" LLC", ", LLC")
            elif r < 0.32:
                nm = nm.rsplit(" ", 1)[0]
            elif r < 0.38:
                nm = nm.upper()
            cry = src["cry"]
            entity = src["BPCNUM_0"]
        else:
            nm = f"{random.choice(CUST_A)} {random.choice(CUST_B)} {random.choice(CUST_C)}"
            cry = random.choice(["US", "US", "CA"])
            entity = f"HS-{cid}"
        truth_customer.append({"source_system": "hubspot", "source_key": cid, "entity_id": entity})
        dom = "".join(ch for ch in nm.lower() if ch.isalnum())[:18] + ".com"
        created = rdate(date(2022, 1, 1), END)
        archived = random.random() < 0.04
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
            "createdate": created, "hs_lastmodifieddate": rdate(created, END),
            "archived": archived,
        })
        meta["hs_company"][cid] = {"created": created,
                                   "archived_on": rdate(created, END) if archived else None}
    hs["company"] = hs_companies

    hs_contacts = []
    for i in range(N_HS_CONTACTS):
        f, last = random.choice(FIRST), random.choice(LAST)
        comp = random.choice(hs_companies)
        dom = comp["domain"] or "example.com"
        email = f"{f.lower()}.{last.lower()}@{dom}"
        if random.random() < 0.05:
            email = None
        created = rdate(date(2022, 1, 1), END)
        archived = random.random() < 0.03
        hs_contacts.append({
            "id": str(12000000000 + i * 773), "email": email, "firstname": f, "lastname": last,
            "jobtitle": random.choice(["Buyer", "Maintenance Manager", "Plant Manager",
                                       "Procurement Lead", "Engineer", "Owner", None]),
            "phone": f"+1{random.randint(2000000000, 9899999999)}" if random.random() < .7 else None,
            "lifecyclestage": choice_w(["subscriber", "lead", "marketingqualifiedlead",
                                        "salesqualifiedlead", "opportunity", "customer"],
                                       [.12, .28, .14, .16, .12, .18]),
            "hs_lead_status": random.choice(["NEW", "OPEN", "IN_PROGRESS", "UNQUALIFIED", None]),
            "hubspot_owner_id": random.choice(OWNER_IDS) if random.random() < .8 else None,
            "associatedcompanyid": comp["id"],
            "createdate": created, "lastmodifieddate": rdate(created, END), "archived": archived,
        })
    for c in random.sample(hs_contacts, 40):          # duplicates: same human, two records
        d = dict(c)
        d["id"] = str(int(c["id"]) + 1)
        d["email"] = (c["email"] or "").replace(".", "_", 1) or None
        d["createdate"] = rdate(c["createdate"], END)
        d["lastmodifieddate"] = rdate(d["createdate"], END)
        hs_contacts.append(d)
    cr = side_rng("contact-deletes")
    for c in hs_contacts:
        archived_on = rdate(c["createdate"], END) if c["archived"] else None
        # 1% are hard-deleted (a privacy request): gone from the API entirely,
        # which only a key reconciliation notices.
        deleted_on = (c["createdate"] + timedelta(days=cr.randint(20, 400))
                      if cr.random() < 0.01 else None)
        meta["hs_contact"][c["id"]] = {"created": c["createdate"], "archived_on": archived_on,
                                       "deleted_on": deleted_on}
    hs["contact"] = hs_contacts

    shipped_orders = [s for s, h in order_index.items() if h["shipped"]]
    hs_deals, hs_stage_hist = [], []
    for i in range(N_HS_DEALS):
        comp = random.choice(hs_companies)
        created = rdate(max(date(2023, 6, 1), comp["createdate"]), END)
        stage = choice_w([s[0] for s in STAGES], [.10, .12, .14, .10, .08, .30, .16])
        is_closed = stage in ("closedwon", "closedlost")
        amt = round(random.lognormvariate(9.6, 0.9), 2)
        erp = None
        if stage == "closedwon" and random.random() < 0.60 and shipped_orders:
            so = random.choice(shipped_orders)
            rr2 = random.random()
            erp = so if rr2 < .72 else (so.lower() if rr2 < .84 else
                                        (f"{so} / {random.choice(shipped_orders)}"
                                         if rr2 < .93 else so[2:]))
        did = str(13000000000 + i * 617)
        owner = random.choice(OWNER_IDS)
        seq = [s[0] for s in STAGES if not s[3]]
        path = seq[:seq.index(stage)] + [stage] if stage in seq else seq + [stage]
        if not is_closed:
            path = seq[:seq.index(stage) + 1]
        t, history = created, []
        for s in path:
            history.append((s, t))
            t = t + timedelta(days=random.randint(2, 45))
        closedate = history[-1][1] if is_closed else t + timedelta(days=random.randint(10, 120))
        for s, at in history:
            hs_stage_hist.append({"deal_id": did, "stage": s, "changed_at": at,
                                  "changed_by_owner_id": owner})
        hs_deals.append({
            "id": did,
            "dealname": f"{comp['name']} - {random.choice(['Q1', 'Q2', 'Q3', 'Q4'])} "
                        f"{random.choice(['Resupply', 'Retrofit', 'New Line', 'Blanket PO', 'Expansion'])}",
            "amount": f"{amt}", "dealstage": stage,
            "pipeline": choice_w([p[0] for p in PIPELINES], [.85, .15]),
            "closedate": closedate, "createdate": created,
            "hs_lastmodifieddate": history[-1][1], "hubspot_owner_id": owner,
            "dealtype": random.choice(["newbusiness", "existingbusiness"]),
            "hs_is_closed_won": stage == "closedwon",
            "hs_deal_stage_probability": str(round(random.uniform(0.05, 0.95), 2)),
            "erp_order_number": erp, "associated_company_id": comp["id"],
            "archived": False,
        })
        meta["deal"][did] = {"created": created, "history": history, "closed": is_closed,
                             "expected_close": created + timedelta(days=random.randint(30, 150))}
    hs["deal"] = hs_deals
    hs["deal_stage_history"] = hs_stage_hist

    contacts_by_company = {}
    for c in hs_contacts:
        contacts_by_company.setdefault(c["associatedcompanyid"], []).append(c)
    hs["association"] = []
    for d in hs_deals:
        hs["association"].append({"from_object_type": "deal", "from_id": d["id"],
                                  "to_object_type": "company", "to_id": d["associated_company_id"],
                                  "association_type": "deal_to_company"})
        pool_c = contacts_by_company.get(d["associated_company_id"], [])
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
        hs["engagement"].append({
            "id": str(14000000000 + i * 331),
            "type": choice_w(["EMAIL", "CALL", "MEETING", "NOTE", "TASK"], [.45, .22, .12, .13, .08]),
            "created_at": rdate(d["createdate"], END), "owner_id": d["hubspot_owner_id"],
            "associated_deal_id": d["id"], "associated_company_id": d["associated_company_id"],
            "body_preview": random.choice(["Follow up on pricing", "Left voicemail",
                                           "Sent revised quote", "Site visit scheduled",
                                           "Awaiting PO", "Discussed lead times"]),
        })

    # ============================================================ NETSTOCK ===
    # Netstock regenerates its whole dataset on each sync. The static parts
    # (which item-locations exist, their forecast levels) are fixed here; the
    # per-sync values are derived from the sync date in `_netstock_as_of`.
    ns_pairs = [(i, f) for i, f in ITEM_SITE if random.random() < 0.97]
    for _ in range(35):                               # orphans: not in the ERP item master
        ns_pairs.append((f"FG-{random.randint(90000, 99999)}", random.choice(SITE_CODES)))
    ns_static = {
        "pairs": ns_pairs, "item_des": ITEM_DES,
        "suppliers": [(s["BPSNUM_0"], s["name"], s["lt"]) for s in suppliers],
        "po_numbers": [(r["POHNUM_0"], r["ORDDAT_0"]) for r in x3["PORDER"]],
        "level": {p: random.uniform(5, 400) for p in ns_pairs},
    }

    # ======================================================== AZURE COSTS ===
    cost_static = {"resources": [
        ("ct-dev-dagster", "Microsoft.App/containerApps", "orchestration", 2.10),
        ("ct-dev-data-service", "Microsoft.App/containerApps", "downstream_apps", 0.55),
        ("ct-dev-pg", "Microsoft.DBforPostgreSQL/flexibleServers", "downstream_apps", 0.85),
        ("ctdevlake", "Microsoft.Storage/storageAccounts", "raw_storage", 0.40),
        ("ct-dev-kv", "Microsoft.KeyVault/vaults", "security", 0.03),
        ("ct-dev-logs", "Microsoft.OperationalInsights/workspaces", "monitoring", 0.70),
        ("ct-dev-swa", "Microsoft.Web/staticSites", "governance", 0.00),
    ]}

    # ============================================================== TRUTH ===
    truth_employee = []
    for p in people:
        truth_employee.append({"source_system": "sage_x3.AUTILIS", "source_key": p["user"],
                               "entity_id": p["entity"]})
        if p["rep"]:
            truth_employee.append({"source_system": "sage_x3.REPRESENT",
                                   "source_key": p["rep"], "entity_id": p["entity"]})
    for o, p in zip(hs["owner"], owner_people):
        truth_employee.append({"source_system": "hubspot", "source_key": o["id"],
                               "entity_id": p["entity"]})
    truth = {
        "customer_identity": truth_customer,
        "employee_identity": truth_employee,
        "employee_department": [{"entity_id": p["entity"],
                                 "department_code": DEPARTMENT_OF_PROFILE[p["profile"]]}
                                for p in people],
    }

    meta["balance_parent"] = balance_parent
    meta["pinv_sources"] = pinv_sources
    meta["memo_by_return"] = memo_by_return
    meta["inv_by_order"] = {soh: num for soh, (num, _) in inv_by_order.items()}
    return Timeline(x3=x3, hs=hs, ns_static=ns_static, cost_static=cost_static,
                    truth=truth, meta=meta)


# ---------------------------------------------------------------------------
# The view of the timeline from one day
# ---------------------------------------------------------------------------
def _keep(rows, pred):
    rows[:] = [r for r in rows if pred(r)]


def _stock_qty(pos, base, as_of):
    """On-hand drifts: about 2% of positions move on any given day after the
    initial load, so STOCK produces a trickle of CDC updates."""
    qty = base
    day = INITIAL_DATE + timedelta(days=1)
    while day <= as_of:
        r = _stable_rng("stock", *pos, day)
        if r.random() < 0.02:
            qty = max(0.0, qty + float(r.randint(-60, 80)))
        day += timedelta(days=1)
    return qty


def state_as_of(tl: Timeline, as_of: date) -> dict[str, dict[str, list[dict]]]:
    """What each source system shows on `as_of`.

    Removes every document dated after `as_of`, rolls back every update after
    it, and applies deletes on or before it. Draws from no shared RNG, so the
    same day always produces the same state.
    """
    if not START <= as_of <= TIMELINE_END:
        raise ValueError(f"as_of must be between {START} and {TIMELINE_END}")
    x3 = copy.deepcopy(tl.x3)
    hs = copy.deepcopy(tl.hs)
    meta = tl.meta

    # --- sales orders: not yet taken, hard-deleted, or not yet shipped/cancelled
    om = meta["order"]
    gone_orders = {s for s, m in om.items()
                   if m["date"] > as_of or (m["delete_on"] and m["delete_on"] <= as_of)}
    for t in ("SORDER", "SORDERQ", "SORDERP"):
        _keep(x3[t], lambda r: r["SOHNUM_0"] not in gone_orders)
    for o in x3["SORDER"]:
        m = om[o["SOHNUM_0"]]
        events = [m["date"]]
        if m["shidat"] != NULL_DATE and m["shidat"] > as_of:
            o["SHIDAT_0"], o["ORDSTA_0"] = NULL_DATE, 1
        elif m["shidat"] != NULL_DATE:
            events.append(m["shidat"])
        if m["cancel_on"]:
            if m["cancel_on"] > as_of:
                o["ORDSTA_0"] = 1
            else:
                events.append(m["cancel_on"])
        if m["invoiced_on"] and m["invoiced_on"] <= as_of:
            o["ORDINVSTA_0"] = 3
            events.append(m["invoiced_on"])
        o["UPDDAT_0"] = max(events)

    # --- deliveries: shipped by today; proof of delivery may still be pending
    gone_sdh = {h["SDHNUM_0"] for h in x3["SDELIVERY"]
                if h["SHIDAT_0"] > as_of or h["SOHNUM_0"] in gone_orders}
    _keep(x3["SDELIVERY"], lambda r: r["SDHNUM_0"] not in gone_sdh)
    _keep(x3["SDELIVERYD"], lambda r: r["SDHNUM_0"] not in gone_sdh)
    for h in x3["SDELIVERY"]:
        if h["DLVDAT_0"] > as_of:
            h["DLVDAT_0"] = NULL_DATE
    shipped_qty = {}
    for d in x3["SDELIVERYD"]:
        k = (d["SOHNUM_0"], d["SOPLIN_0"])
        shipped_qty[k] = shipped_qty.get(k, 0.0) + d["QTY_0"]
    for q in x3["SORDERQ"]:
        q["SHTQTY_0"] = max(0.0, q["QTY_0"] - shipped_qty.get((q["SOHNUM_0"], q["SOPLIN_0"]), 0.0))

    # --- sales invoices and credit memos raised by today; payments received by today
    gone_inv = {v["NUM_0"] for v in x3["SINVOICEV"] if v["INVDAT_0"] > as_of}
    _keep(x3["SINVOICEV"], lambda r: r["NUM_0"] not in gone_inv)
    _keep(x3["SINVOICED"], lambda r: r["NUM_0"] not in gone_inv)
    for v in x3["SINVOICEV"]:
        if v["PAYDAT_0"] != NULL_DATE and v["PAYDAT_0"] > as_of:
            v["PAYDAT_0"] = NULL_DATE

    gone_rtn = {r["SRHNUM_0"] for r in x3["SRETURN"] if r["RTNDAT_0"] > as_of}
    _keep(x3["SRETURN"], lambda r: r["SRHNUM_0"] not in gone_rtn)
    _keep(x3["SRETURND"], lambda r: r["SRHNUM_0"] not in gone_rtn)

    # --- purchasing
    _keep(x3["PORDER"], lambda r: r["ORDDAT_0"] <= as_of)
    live_po = {p["POHNUM_0"] for p in x3["PORDER"]}
    _keep(x3["PORDERQ"], lambda r: r["POHNUM_0"] in live_po)
    gone_rcp = {r["PTHNUM_0"] for r in x3["PRECEIPT"] if r["RCPDAT_0"] > as_of}
    gone_rcp |= {b for b, parent in meta["balance_parent"].items() if parent in gone_rcp}
    _keep(x3["PRECEIPT"], lambda r: r["PTHNUM_0"] not in gone_rcp)
    _keep(x3["PRECEIPTD"], lambda r: r["PTHNUM_0"] not in gone_rcp)
    received = {(d["POHNUM_0"], d["POPLIN_0"]) for d in x3["PRECEIPTD"]}
    for ln in x3["PORDERQ"]:
        if (ln["POHNUM_0"], ln["POPLIN_0"]) not in received:
            ln["RCPQTY_0"], ln["RCPDAT_0"] = 0.0, NULL_DATE
    gone_pinv = {v["NUM_0"] for v in x3["PINVOICE"] if v["INVDAT_0"] > as_of}
    gone_pinv |= {n for n, srcs in meta["pinv_sources"].items() if srcs & gone_rcp}
    _keep(x3["PINVOICE"], lambda r: r["NUM_0"] not in gone_pinv)
    _keep(x3["PINVOICED"], lambda r: r["NUM_0"] not in gone_pinv)

    # --- GL: postings whose document exists
    gone_gl = {g["NUM_0"] for g in x3["GACCENTRY"]
               if g["ACCDAT_0"] > as_of or g["VCRNUM_0"] in gone_inv
               or g["VCRNUM_0"] in gone_pinv}
    _keep(x3["GACCENTRY"], lambda r: r["NUM_0"] not in gone_gl)
    _keep(x3["GACCENTRYD"], lambda r: r["NUM_0"] not in gone_gl)

    # --- counts: counted by today, posted three days after counting
    _keep(x3["STOCOUNT"], lambda r: r["CNTDAT_0"] <= as_of)
    live_ses = {s["SESNUM_0"] for s in x3["STOCOUNT"]}
    _keep(x3["STOCOUNTD"], lambda r: r["SESNUM_0"] in live_ses)
    for s in x3["STOCOUNT"]:
        if s["CNTDAT_0"] + timedelta(days=3) > as_of:
            s["SESSTA_0"] = 2

    # --- stock journal: movements dated by today whose document exists
    _keep(x3["STOJOU"], lambda r: r["IPTDAT_0"] <= as_of
          and not (r["VCRTYP_0"] == "SDH" and r["VCRNUM_0"] in gone_sdh)
          and not (r["VCRTYP_0"] == "SRH" and r["VCRNUM_0"] in gone_rtn)
          and not (r["VCRTYP_0"] == "PTH" and r["VCRNUM_0"] in gone_rcp))
    for r in x3["STOCK"]:
        r["QTYSTU_0"] = _stock_qty((r["STOFCY_0"], r["ITMREF_0"], r["LOT_0"], r["LOC_0"]),
                                   r["QTYSTU_0"], as_of)

    # --- masters: an update after today has not happened yet
    for it in x3["ITMMASTER"]:
        m = meta["item"][it["ITMREF_0"]]
        if m["changed_on"] > as_of:
            if it["ITMSTA_0"] == 3:
                it["ITMSTA_0"] = m["prev_status"]
            it["UPDDAT_0"] = it["CREDAT_0"]
    for c in x3["BPCUSTOMER"]:
        m = meta["customer"][c["BPCNUM_0"]]
        if m["changed_on"] > as_of:
            c["REP_0"] = m["prev_rep"]
            c["UPDDAT_0"] = c["CREDAT_0"]

    # --- HubSpot
    hm = meta["hs_company"]
    _keep(hs["company"], lambda r: hm[r["id"]]["created"] <= as_of)
    for c in hs["company"]:
        a = hm[c["id"]]["archived_on"]
        c["archived"] = bool(a and a <= as_of)
        changes = [c["createdate"]] + [d for d in (c["hs_lastmodifieddate"], a)
                                       if d and d <= as_of]
        c["hs_lastmodifieddate"] = max(changes)
    cm = meta["hs_contact"]
    _keep(hs["contact"], lambda r: cm[r["id"]]["created"] <= as_of
          and not (cm[r["id"]]["deleted_on"] and cm[r["id"]]["deleted_on"] <= as_of))
    for c in hs["contact"]:
        a = cm[c["id"]]["archived_on"]
        c["archived"] = bool(a and a <= as_of)
        changes = [c["createdate"]] + [d for d in (c["lastmodifieddate"], a) if d and d <= as_of]
        c["lastmodifieddate"] = max(changes)
    dm = meta["deal"]
    _keep(hs["deal"], lambda r: dm[r["id"]]["created"] <= as_of)
    for d in hs["deal"]:
        hist = [(s, t) for s, t in dm[d["id"]]["history"] if t <= as_of]
        d["dealstage"] = hist[-1][0]
        d["hs_lastmodifieddate"] = hist[-1][1]
        d["hs_is_closed_won"] = d["dealstage"] == "closedwon"
        if d["dealstage"] != "closedwon":
            d["erp_order_number"] = None
        if d["dealstage"] not in ("closedwon", "closedlost"):
            # An open deal shows its expected close date, which goes stale
            # when nobody updates it - common, and visible as a past date.
            d["closedate"] = dm[d["id"]]["expected_close"]
    _keep(hs["deal_stage_history"], lambda r: r["changed_at"] <= as_of)
    live = ({c["id"] for c in hs["company"]} | {c["id"] for c in hs["contact"]}
            | {d["id"] for d in hs["deal"]})
    _keep(hs["association"], lambda r: r["from_id"] in live and r["to_id"] in live)
    live_deals = {d["id"] for d in hs["deal"]}
    _keep(hs["engagement"], lambda r: r["created_at"] <= as_of
          and r["associated_deal_id"] in live_deals)

    return {
        "sage_x3": x3,
        "hubspot": hs,
        "netstock": _netstock_as_of(tl.ns_static, as_of),
        "azure_cost": _costs_as_of(tl.cost_static, as_of),
    }


def _netstock_as_of(st: dict, as_of: date) -> dict[str, list[dict]]:
    """Netstock as it looks after its most recent sync. It syncs every night
    and lags the ERP by two days by construction."""
    sync = as_of - timedelta(days=2)
    ns: dict = {}
    ns["supplier"] = [{"supplier_code": code, "supplier_name": name, "lead_time_days": lt,
                       "min_order_value": float(_stable_rng("ns-sup", code).choice([0, 500, 2500])),
                       "source_system": "SAGEX3"} for code, name, lt in st["suppliers"]]
    sup_codes = [s[0] for s in st["suppliers"]]
    known_pos = sorted(po for po, ordered in st["po_numbers"] if ordered <= sync)
    ns["item_location"] = []
    for itm, fcy in st["pairs"]:
        fixed = _stable_rng("ns-il", itm, fcy)
        daily = _stable_rng("ns-il", itm, fcy, sync)
        ns["item_location"].append({
            "item_code": itm, "location_code": fcy,
            "description": st["item_des"].get(itm, "UNKNOWN - not in ERP master"),
            "abc_class": fixed.choices(["A", "B", "C"], [.2, .3, .5])[0],
            "xyz_class": fixed.choices(["X", "Y", "Z"], [.35, .4, .25])[0],
            "policy": fixed.choices(["MIN_MAX", "ROP", "FORECAST"], [.3, .4, .3])[0],
            "lead_time_days": fixed.randint(3, 75),
            "safety_stock_qty": float(fixed.randint(0, 500)),
            "reorder_point_qty": float(fixed.randint(50, 1500)),
            "min_order_qty": float(fixed.choice([1, 10, 25, 50, 100])),
            "supplier_code": fixed.choice(sup_codes),
            "on_hand_qty": float(daily.randint(0, 4000)),
            "on_order_qty": float(daily.randint(0, 1500)),
            "excess_value": money(daily.uniform(0, 45000)) if daily.random() < .3 else 0.0,
            "stockout_risk": daily.choices(["LOW", "MEDIUM", "HIGH"], [.6, .28, .12])[0],
            "last_sync_at": sync,
        })
    first_month = date(2025, 9, 1)
    months, m = [], first_month
    for _ in range(24):
        months.append(m)
        m = date(m.year + m.month // 12, m.month % 12 + 1, 1)
    this_month = date(sync.year, sync.month, 1)
    ns["forecast"], ns["forecast_accuracy"] = [], []
    for itm, fcy in st["pairs"]:
        lvl = st["level"][(itm, fcy)]
        for per in months:
            r = _stable_rng("ns-fc", itm, fcy, per)
            fq = round(max(0.0, lvl * (1 + 0.25 * math.sin(per.month / 12 * 2 * math.pi))
                           * r.uniform(.7, 1.3)), 2)
            ns["forecast"].append({
                "item_code": itm, "location_code": fcy, "period_start": per,
                "period_type": "MONTH", "forecast_qty": fq,
                "forecast_method": r.choices(["CROSTON", "HOLT_WINTERS", "MOVING_AVG", "MANUAL"],
                                             [.2, .35, .35, .10])[0],
                "generated_at": sync,
            })
            if per < this_month:                 # actuals exist for completed months only
                act = round(max(0.0, fq * r.uniform(.45, 1.65)), 2)
                ns["forecast_accuracy"].append({
                    "item_code": itm, "location_code": fcy, "period_start": per,
                    "forecast_qty": fq, "actual_qty": act,
                    "abs_pct_error": round(abs(act - fq) / fq * 100, 2) if fq else None,
                })
    ns["replenishment_recommendation"] = []
    picker = _stable_rng("ns-rec")
    chosen = picker.sample(st["pairs"], min(900, len(st["pairs"])))
    for k, (itm, fcy) in enumerate(chosen):
        r = _stable_rng("ns-rec", k, sync)
        ns["replenishment_recommendation"].append({
            "recommendation_id": f"REC{k:07d}", "item_code": itm, "location_code": fcy,
            "recommended_qty": float(r.randint(25, 2000)),
            "recommended_order_date": sync + timedelta(days=r.randint(-20, 30)),
            "required_date": sync + timedelta(days=r.randint(10, 90)),
            "supplier_code": r.choice(sup_codes),
            "status": r.choices(["OPEN", "ACCEPTED", "REJECTED", "EXPIRED"], [.5, .3, .1, .1])[0],
            "erp_po_number": r.choice(known_pos) if r.random() < .25 else None,
            "generated_at": sync,
        })
    return ns


def _costs_as_of(st: dict, as_of: date) -> dict[str, list[dict]]:
    """A daily Azure Cost Management export in FOCUS shape, one day behind."""
    rows = []
    day = INITIAL_DATE - timedelta(days=60)
    while day < as_of:
        for name, rtype, component, daily in st["resources"]:
            r = _stable_rng("cost", name, day)
            cost = round(daily * r.uniform(0.85, 1.2), 4)
            rows.append({
                "ChargePeriodStart": day, "ChargePeriodEnd": day + timedelta(days=1),
                "ResourceName": name, "ResourceType": rtype, "ServiceCategory": rtype.split("/")[0],
                "BilledCost": cost, "EffectiveCost": cost, "BillingCurrency": "USD",
                "Tags": f'{{"env":"dev","component":"{component}","stack":"oss-baseline"}}',
                "x_Component": component, "x_Environment": "dev",
            })
        day += timedelta(days=1)
    return {"focus_cost": rows}
