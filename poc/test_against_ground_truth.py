"""
test_against_ground_truth.py — Automated tester against real DEVIS data
=========================================================================

Takes N REAL projects from the parsed yearly data, uses each project's
client_request as pipeline input, and compares the LLM-generated
configuration against the project's actual Excel BoM, hours and price.

Produces a report scored on the SAME six dimensions as the human feedback
Excel (Compréhension / Projets similaires / Armoire / BoM / Heures / Prix),
each rated 1-5 using the exact Notation Guide thresholds from that file.

The test project is NEVER allowed to retrieve itself (post-hoc removal from
retrieval results — mathematically equivalent to holdout for k-NN).

Usage
-----
    python3 poc/test_against_ground_truth.py                   # default: 10 random
    python3 poc/test_against_ground_truth.py --year 2026 --n 15
    python3 poc/test_against_ground_truth.py --ids DEVIS2601101,DEVIS2601138
    python3 poc/test_against_ground_truth.py --csv report.csv  # Excel-compatible
    python3 poc/test_against_ground_truth.py --json report.json
    python3 poc/test_against_ground_truth.py --quick           # skip LLM (metrics only)

Scoring matches the tester feedback rubric exactly:
  Compréhension:  5 = all params + implicit constraints
  RAG @1 sim:     ≥0.85 → 5, ≥0.75 → 4, ≥0.65 → 3, ≥0.55 → 2, else 1
  Armoire:        type match + dimension proxy
  BoM:            category F1-based
  Hours Fab MAPE: <5% → 5, <15% → 4, <30% → 3, <50% → 2, else 1
  Price MAPE:     <5% → 5, <10% → 4, <25% → 3, <40% → 2, else 1
"""

import argparse
import json
import os
import random
import re
import sys
import time
import csv as _csv
from pathlib import Path
from statistics import mean, median

# ── Env bootstrap ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
env_path = BASE_DIR / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(BASE_DIR))
import anthropic
import app
import rag

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


CHASSIS_SUBS = {"04_internal_chassis_power",
                "04_internal_chassis_control",
                "04_internal_chassis_automation"}


# ══════════════════════════════════════════════════════════════════════════
# Pipeline execution (same flow as the production app.py streaming endpoint)
# ══════════════════════════════════════════════════════════════════════════

def extract_requirements(request: str) -> dict:
    prompt = f"""Extract key technical requirements from this CETIE customer request:

<request>
{request[:1500]}
</request>

Respond ONLY with JSON:
{{"product_type":"brief","power_kw":null_or_number,"nb_motors":null_or_number,
"voltage":null_or_string,"ip_rating":null_or_string,"automation":null_or_string,
"sector":null_or_string,"keywords":["..."],"summary":"1 sentence"}}"""
    # temperature=0 → deterministic output so A/B comparisons isolate rule effects
    # rather than run-to-run LLM variance.
    msg = client.messages.create(model="claude-sonnet-4-6", max_tokens=500,
                                  temperature=0,
                                  messages=[{"role": "user", "content": prompt}])
    try:
        from json_repair import repair_json
        return json.loads(repair_json(msg.content[0].text))
    except Exception:
        return {"keywords": [], "summary": request[:100]}


def retrieve_excluding(request: str, exclude_id: str, n: int = 5) -> list:
    """Retrieve similar projects, post-hoc remove the test project."""
    out = []
    for year in ["2022", "2026"]:
        try:
            for h in rag.retrieve_similar_projects(request, year=year, n_results=n + 1):
                if h.get("id") == exclude_id:
                    continue
                h["_year"] = year
                out.append(h)
        except Exception:
            pass
    out.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)
    return out[:n]


def _full_bom_text(conf: dict, max_per_cat: int = 25) -> str:
    """Render a full BoM, up to max_per_cat items per category."""
    cats = conf.get("by_category", {})
    lines = []
    for cat, items in cats.items():
        if items:
            lines.append(f"  [{cat}]:")
            for it in items[:max_per_cat]:
                q = it.get("quantity", 1)
                d = it.get("designation", "")
                up = it.get("unit_price", 0) or 0
                lines.append(f"    - {q}x {d} @ {up:.2f}€")
    return "\n".join(lines) if lines else "  (empty)"


def build_yearly_section(projects: list) -> str:
    """
    Template-based context:
      • TOP-1 DEVIS becomes the EXPLICIT base template to copy-and-adjust.
      • The next 2 DEVIS are additional references for variation.
    This framing pushes the LLM toward completeness (keep the template items
    unless the request contradicts them) rather than synthesis-from-scratch.
    """
    if not projects:
        return ""

    # ── Top-1 = template ─────────────────────────────────────────────────────
    p0 = projects[0]
    c0 = p0.get("configuration", {})
    n_items0 = sum(len(v) for v in c0.get("by_category", {}).values() if isinstance(v, list))
    template_block = (
        f"━━━ BASE TEMPLATE — start from this DEVIS's BoM ━━━\n"
        f"DEVIS {p0.get('id','')[:30]}  |  Client: {p0.get('client','')}\n"
        f"Description: {p0.get('description','')}\n"
        f"Similarity to current request: {p0['similarity_score']:.0%}  |  "
        f"Items in this DEVIS: {n_items0}\n"
        f"Fabrication: {c0.get('hours_fabrication',0)}h  |  "
        f"Prog: {c0.get('hours_programmation',0)}h  |  "
        f"Matière: {c0.get('cost_material',0):.0f}€  |  "
        f"Prix devis: {c0.get('base_price',0):.0f}€\n\n"
        f"TEMPLATE BoM — use this as your starting list:\n"
        f"{_full_bom_text(c0, max_per_cat=25)}\n\n"
        f"HOW TO USE THIS TEMPLATE:\n"
        f"  1. Start from the template items above — they represent a known-good "
        f"configuration for a similar request.\n"
        f"  2. KEEP every item whose function is needed by the current request.\n"
        f"  3. REPLACE items where the specs differ (e.g. change pump power, "
        f"swap automate brand if the request asks for a different one).\n"
        f"  4. ADD any items required by the current request that the template "
        f"lacks, including accessory items from the knowledge rules below.\n"
        f"  5. REMOVE items only when the current request clearly doesn't need them.\n"
        f"  6. Base your hours/price estimates on the template's values, adjusted "
        f"proportionally for scale and complexity differences.\n"
    )

    # ── Additional references (2-3 more) ─────────────────────────────────────
    refs = []
    for i, p in enumerate(projects[1:3], start=2):
        conf = p.get("configuration", {})
        n = sum(len(v) for v in conf.get("by_category", {}).values() if isinstance(v, list))
        refs.append(
            f"--- Reference DEVIS #{i} (sim: {p['similarity_score']:.0%}, {n} items) ---\n"
            f"Client: {p.get('client','')} | {p.get('description','')[:60]}\n"
            f"Fab: {conf.get('hours_fabrication',0)}h | Prog: {conf.get('hours_programmation',0)}h | "
            f"Matière: {conf.get('cost_material',0):.0f}€\n"
            f"BoM:\n{_full_bom_text(conf, max_per_cat=15)}"
        )
    refs_block = ""
    if refs:
        refs_block = "\n━━━ ADDITIONAL REFERENCES (for variation, not templates) ━━━\n" + "\n\n".join(refs) + "\n"

    return "\n" + template_block + refs_block


def generate_config(request: str, requirements: dict, yearly: str, accessories: str) -> dict:
    prompt = f"""You are a CETIE technical expert configuring electrical control panels.

Customer request: {request[:1500]}

Extracted requirements:
{json.dumps(requirements, ensure_ascii=False)}
{yearly}{accessories}
GROUNDING RULES (apply to every item you output):
 1. You are adapting the BASE TEMPLATE above, NOT designing from scratch. Preserve every template item unless the current request clearly contradicts it.
 2. Component designations must come from the template, an Additional Reference, or the CETIE catalogue. Do not invent or paraphrase.
 3. Every item must have a "source" field: "devis:<DEVIS-id>" (name the DEVIS it came from) or "catalogue".
 4. Your hours and price estimates MUST be anchored to the template's values, adjusted proportionally for real differences between the two requests (motor count, power, automation brand). Do not underestimate.

Respond ONLY with JSON:
{{
  "bom_categories":{{
    "01_cabinet_enclosure":[],"02_equipment_on_side":[],"04_internal_chassis_power":[],
    "04_internal_chassis_control":[],"04_internal_chassis_automation":[],
    "05_equipment_on_top":[],"06_door_controls":[],"06_door_controls_power":[],
    "07_supplied_separately":[],"09_commissioning":[],"10_packaging":[],
    "11_labor":[{{"designation":"Main d'œuvre câblage","quantity":1,"hours":0}},{{"designation":"Main d'œuvre programmation","quantity":1,"hours":0}}],
    "12_options":[]
  }},
  "total_hours_cablage":number,"total_hours_prog":number,
  "estimated_material_cost":number,"estimated_price":number,
  "assumptions":["..."],"missing_info":["..."],"expert_notes":"..."
}}

Each item: {{"designation":"exact","quantity":N,"unit_price":€,"source":"devis:... or catalogue"}}"""
    msg = client.messages.create(model="claude-opus-4-7", max_tokens=6000,
                                  temperature=0,
                                  messages=[{"role": "user", "content": prompt}])
    try:
        from json_repair import repair_json
        return json.loads(repair_json(msg.content[0].text))
    except Exception as e:
        return {"error": str(e), "raw": msg.content[0].text[:500]}


# ══════════════════════════════════════════════════════════════════════════
# Scoring (matches the Notation Guide sheet in CETIE Feedback Testeurs.xlsx)
# ══════════════════════════════════════════════════════════════════════════

def score_understanding(gt: dict, llm_req: dict, request: str) -> tuple[int, str]:
    """Compare extracted requirements vs ground truth metadata.
    Only checks what the REQUEST ITSELF makes extractable — we don't penalise
    the LLM for missing implementation details (e.g. a brand) that the customer
    never mentioned in the first place.
    """
    checks = []
    req_low = request.lower()

    # nb_motors — check only if mentioned in the request
    gt_m = gt.get("nb_motors")
    if gt_m and re.search(r"\d+\s*(pompes|motors|motor|moteurs|moteur)", req_low):
        llm_m = llm_req.get("nb_motors")
        checks.append(("nb_motors", gt_m == llm_m))

    # metier/sector — check only if the request suggests one
    gt_sector = (gt.get("metier") or gt.get("sector") or "").lower()
    llm_sector = (llm_req.get("sector") or "").lower()
    if gt_sector and llm_sector:
        match = gt_sector in llm_sector or llm_sector in gt_sector
        checks.append(("sector", match))

    # Brand/automation detection — only for brands the REQUEST mentions explicitly.
    # This way the LLM isn't penalised for not guessing a brand the customer omitted.
    brand_keywords = [
        ("s4w", ["s4w", "sofrel"]),
        ("s7-1200", ["s7-1200", "s7 1200", "simatic"]),
        ("millenium", ["millenium", "millénium"]),
        ("zelio", ["zelio", "zélio"]),
        ("logo", ["logo!", "logo 8"]),
        ("variateur", ["variateur", "atv630", "atv320", "altivar", "vfd"]),
        ("démarreur", ["démarreur", "demarreur", "ats01", "ats22", "ats490", "soft start"]),
    ]
    llm_auto = (llm_req.get("automation") or "").lower()
    llm_kw = " ".join(llm_req.get("keywords", [])).lower()
    for brand_tag, patterns in brand_keywords:
        in_request = any(p in req_low for p in patterns)
        if in_request:
            in_llm = any(p in llm_auto or p in llm_kw for p in patterns)
            checks.append((f"brand[{brand_tag}]", in_llm))

    # IP rating — check only if request mentions one
    ip_in_req = re.search(r"ip\s?\d{2}", req_low)
    if ip_in_req:
        llm_ip = (llm_req.get("ip_rating") or "").lower()
        checks.append(("ip_rating", bool(llm_ip)))

    if not checks:
        return 3, "no extractable signals in request"

    passed = sum(1 for _, ok in checks if ok)
    ratio = passed / len(checks)
    if ratio >= 0.95: score = 5
    elif ratio >= 0.75: score = 4
    elif ratio >= 0.50: score = 3
    elif ratio >= 0.25: score = 2
    else: score = 1
    detail = ", ".join(f"{name}={'✓' if ok else '✗'}" for name, ok in checks)
    return score, detail


def score_retrieval(top_sim: float, top_product_type: str, gt_product_type: str) -> tuple[int, str]:
    """Retrieval quality — primary signal is top-1 cosine similarity."""
    if top_sim >= 0.85: base = 5
    elif top_sim >= 0.75: base = 4
    elif top_sim >= 0.65: base = 3
    elif top_sim >= 0.55: base = 2
    else: base = 1
    # Penalise if top product_type doesn't match
    type_match = top_product_type and gt_product_type and (
        top_product_type.lower() in gt_product_type.lower() or
        gt_product_type.lower() in top_product_type.lower()
    )
    if not type_match and base > 2:
        base -= 1
    detail = f"top_sim={top_sim:.3f}, type_match={'✓' if type_match else '✗'}"
    return base, detail


def _enclosure_signature(bom: dict) -> str:
    """Extract a short signature from the 01_cabinet_enclosure category."""
    items = bom.get("01_cabinet_enclosure", []) or []
    if not items:
        return ""
    # Use main enclosure line (longest designation typically)
    main = max(items, key=lambda x: len(x.get("designation", "")), default={})
    return (main.get("designation") or "").lower()


def score_enclosure(gt_bom: dict, llm_bom: dict) -> tuple[int, str]:
    """Compare enclosure type + rough dimension proxy."""
    gt_sig = _enclosure_signature(gt_bom)
    llm_sig = _enclosure_signature(llm_bom)
    if not gt_sig and not llm_sig:
        return 3, "no enclosure data"
    if not gt_sig or not llm_sig:
        return 2, f"gt='{gt_sig[:40]}', llm='{llm_sig[:40]}'"

    # Material/type match: polyester / acier / coffret / armoire / cellule / inox / alu
    type_keywords = ["polyester", "acier", "inox", "aluminium", "cellule",
                     "coffret", "armoire"]
    gt_types = {t for t in type_keywords if t in gt_sig}
    llm_types = {t for t in type_keywords if t in llm_sig}
    if not gt_types:
        type_match = 0.5
    else:
        type_match = len(gt_types & llm_types) / len(gt_types)

    # Dimension proxy: extract WxHxD patterns and compare
    def _extract_dims(s):
        m = re.findall(r"(\d{3,4})\s*x\s*(\d{3,4})", s)
        return [(int(a), int(b)) for a, b in m]
    gt_dims = _extract_dims(gt_sig)
    llm_dims = _extract_dims(llm_sig)
    dim_close = True
    if gt_dims and llm_dims:
        g = gt_dims[0]; l = llm_dims[0]
        # within 30%
        dim_close = (abs(g[0] - l[0]) / max(g[0], 1) < 0.30 and
                     abs(g[1] - l[1]) / max(g[1], 1) < 0.30)

    if type_match == 1 and dim_close:
        score = 5 if gt_dims and llm_dims else 4
    elif type_match >= 0.5 and dim_close:
        score = 4
    elif type_match >= 0.5:
        score = 3
    elif type_match > 0:
        score = 2
    else:
        score = 1
    detail = (f"type_match={type_match:.0%}, dims={'close' if dim_close else 'off'}, "
              f"gt='{list(gt_types)}' llm='{list(llm_types)}'")
    return score, detail


def _expand_cats(cats: set) -> set:
    """Expand legacy 04_internal_chassis → its 3 sub-categories."""
    out = set()
    for c in cats:
        if c == "04_internal_chassis":
            out |= CHASSIS_SUBS
        else:
            out.add(c)
    out.discard("04_internal_chassis")
    return out


def score_bom(gt_bom: dict, llm_bom: dict) -> tuple[int, str]:
    """
    BoM quality score.

    Priority: RECALL of ground-truth items. If the LLM produces everything
    the real DEVIS has, that's excellent. Producing a few additional items
    is acceptable (often means the LLM added accessories the original
    estimator forgot — this is DESIRED behaviour, not a regression).

    We penalise extras only when they dramatically outnumber real items
    (signal of over-generation / hallucination).
    """
    gt_cats = _expand_cats({c for c, items in gt_bom.items() if items})
    llm_cats = _expand_cats({c for c, items in llm_bom.items()
                             if isinstance(items, list) and items})
    if not gt_cats:
        return 3, "no ground-truth categories"

    # Category recall: what fraction of GT categories did the LLM populate?
    cat_recall = len(gt_cats & llm_cats) / len(gt_cats)

    # Designation recall (primary metric): what fraction of GT item designations
    # are found in the LLM output?
    gt_des = []
    for items in gt_bom.values():
        if items:
            for it in items:
                d = (it.get("designation") or "").lower().strip()
                if d:
                    # Use first 5 meaningful words for substring matching
                    gt_des.append(" ".join(d.split()[:5]))

    llm_flat = " ".join(
        (it.get("designation") or "").lower()
        for items in llm_bom.values() if isinstance(items, list)
        for it in items
    )
    matched = sum(1 for d in gt_des if d and d in llm_flat)
    des_recall = matched / len(gt_des) if gt_des else 0

    # Over-generation penalty (mild): only applies if LLM has > 2× the GT items
    gt_count = sum(len(v) for v in gt_bom.values() if isinstance(v, list))
    llm_count = sum(len(v) for v in llm_bom.values() if isinstance(v, list))
    ratio = llm_count / max(gt_count, 1)
    over_penalty = 0
    if ratio > 2.0:  # only a HEAVY ratio triggers a penalty
        over_penalty = min(0.15, (ratio - 2.0) * 0.05)

    # Combined score, recall-heavy
    combined = (0.4 * cat_recall + 0.6 * des_recall) - over_penalty

    if combined >= 0.85: score = 5
    elif combined >= 0.70: score = 4
    elif combined >= 0.50: score = 3
    elif combined >= 0.30: score = 2
    else: score = 1
    detail = (f"cat_recall={cat_recall:.0%}, des_recall={des_recall:.0%}, "
              f"items={llm_count}/{gt_count}, combined={combined:.2f}")
    return score, detail


def _mape(llm: float, gt: float) -> float:
    if not gt:
        return float("inf")
    return abs(llm - gt) / abs(gt) * 100


def score_hours(gt_fab: float, llm_fab: float) -> tuple[int, str]:
    if not gt_fab:
        return 3, "no GT hours"
    m = _mape(llm_fab or 0, gt_fab)
    if m < 5: score = 5
    elif m < 15: score = 4
    elif m < 30: score = 3
    elif m < 50: score = 2
    else: score = 1
    return score, f"gt={gt_fab}h, llm={llm_fab}h, MAPE={m:.0f}%"


def score_price(gt_price: float, llm_price: float) -> tuple[int, str]:
    if not gt_price:
        return 3, "no GT price"
    m = _mape(llm_price or 0, gt_price)
    if m < 5: score = 5
    elif m < 10: score = 4
    elif m < 25: score = 3
    elif m < 40: score = 2
    else: score = 1
    return score, f"gt={gt_price:.0f}€, llm={llm_price:.0f}€, MAPE={m:.0f}%"


# ══════════════════════════════════════════════════════════════════════════
# Per-project run
# ══════════════════════════════════════════════════════════════════════════

def run_case(project: dict, year: str, quick: bool = False) -> dict:
    t0 = time.time()
    pid = project.get("id", "")
    request = (project.get("client_request") or "").strip()
    if len(request) < 50:
        # Fall back to description + divalto_designation if the email body is thin
        request = " | ".join(filter(None, [
            project.get("divalto_designation"),
            project.get("description"),
            project.get("product"),
        ]))

    # Ground truth
    conf = project.get("configuration", {})
    gt = {
        "id": pid,
        "year": year,
        "client": project.get("client") or "",
        "description": project.get("description") or project.get("divalto_designation") or "",
        "product_type": project.get("product_type") or "",
        "metier": project.get("metier") or "",
        "nb_motors": project.get("nb_motors"),
        "tags": project.get("tags") or [],
        "base_price": conf.get("base_price") or 0,
        "cost_material": conf.get("cost_material") or 0,
        "hours_fabrication": conf.get("hours_fabrication") or 0,
        "hours_programmation": conf.get("hours_programmation") or 0,
        "nb_components": conf.get("nb_components") or 0,
        "bom": conf.get("by_category") or {},
    }

    # 1. Requirements extraction
    reqs = extract_requirements(request)

    # 2. Retrieval (excluding the test project itself)
    projects = retrieve_excluding(request, exclude_id=pid, n=5)

    # 3. Accessory rules
    acc_section = app.get_applicable_accessories(request)

    # Score non-LLM dimensions first
    top_sim = projects[0].get("similarity_score") if projects else 0
    top_type = projects[0].get("product_type") if projects else ""

    scores = {}
    details = {}
    scores["comprehension"], details["comprehension"] = score_understanding(gt, reqs, request)
    scores["retrieval"],     details["retrieval"]     = score_retrieval(top_sim, top_type, gt["product_type"])

    if quick:
        elapsed = round(time.time() - t0, 1)
        return {
            "id": pid, "year": year, "client": gt["client"],
            "request_preview": request[:200],
            "gt": {k: v for k, v in gt.items() if k != "bom"},
            "llm_requirements": reqs,
            "retrieved": [{"id": p.get("id"), "sim": p.get("similarity_score"),
                           "type": p.get("product_type")} for p in projects],
            "scores": scores, "details": details,
            "overall": round(mean(scores.values()), 2),
            "elapsed_s": elapsed, "quick_mode": True,
        }

    # 4. Full config generation
    yearly = build_yearly_section(projects)
    cfg = generate_config(request, reqs, yearly, acc_section)
    if "error" in cfg:
        elapsed = round(time.time() - t0, 1)
        return {"id": pid, "year": year, "client": gt["client"],
                "error": cfg["error"], "elapsed_s": elapsed,
                "scores": scores, "details": details}

    llm_bom = cfg.get("bom_categories", {})
    llm_fab = cfg.get("total_hours_cablage") or 0
    llm_price_mat = cfg.get("estimated_material_cost") or 0
    llm_price_devis = cfg.get("estimated_price") or 0

    scores["enclosure"], details["enclosure"] = score_enclosure(gt["bom"], llm_bom)
    scores["bom"],       details["bom"]       = score_bom(gt["bom"], llm_bom)
    scores["hours"],     details["hours"]     = score_hours(gt["hours_fabrication"], llm_fab)
    # Compare price matière when GT has cost_material, else fall back to base_price
    gt_price_ref = gt["cost_material"] or gt["base_price"]
    llm_price_ref = llm_price_mat or llm_price_devis
    scores["price"],     details["price"]     = score_price(gt_price_ref, llm_price_ref)

    elapsed = round(time.time() - t0, 1)
    return {
        "id": pid,
        "year": year,
        "client": gt["client"],
        "request_preview": request[:250],
        "gt_summary": {
            "description": gt["description"][:80],
            "hours_fab": gt["hours_fabrication"],
            "hours_prog": gt["hours_programmation"],
            "base_price": gt["base_price"],
            "cost_material": gt["cost_material"],
            "nb_components": gt["nb_components"],
            "categories": sorted(_expand_cats({c for c, items in gt["bom"].items() if items})),
        },
        "llm_summary": {
            "hours_fab": llm_fab,
            "hours_prog": cfg.get("total_hours_prog") or 0,
            "estimated_price": llm_price_devis,
            "estimated_material_cost": llm_price_mat,
            "nb_items": sum(len(v) for v in llm_bom.values() if isinstance(v, list)),
            "categories": sorted(_expand_cats({c for c, items in llm_bom.items()
                                              if isinstance(items, list) and items})),
        },
        "retrieved_top3": [{"id": p.get("id")[:35], "sim": round(p.get("similarity_score", 0), 3),
                            "type": p.get("product_type")} for p in projects[:3]],
        "accessories_matched": re.findall(r"▪ ([^(]+?)\s+\(", acc_section),
        "scores": scores,
        "details": details,
        "overall": round(mean(scores.values()), 2),
        "elapsed_s": elapsed,
    }


# ══════════════════════════════════════════════════════════════════════════
# Reporting
# ══════════════════════════════════════════════════════════════════════════

DIMENSIONS = ["comprehension", "retrieval", "enclosure", "bom", "hours", "price"]
DIM_LABELS = {
    "comprehension": "Compréhension",
    "retrieval":     "Projets similaires",
    "enclosure":     "Armoire",
    "bom":           "BoM composants",
    "hours":         "Heures câblage",
    "price":         "Prix matière",
}


def print_case(r: dict):
    print(f"\n{'─' * 78}")
    print(f" [{r['id'][:40]}]  {r.get('client', '?')}  ({r.get('year', '?')})")
    print('─' * 78)
    if "error" in r:
        print(f"  ✗ ERROR: {r['error']}")
        return
    print(f"  Request: {r.get('request_preview', '')[:150]}")
    gt_s = r.get("gt_summary", {})
    llm_s = r.get("llm_summary", {})
    print(f"\n  GT        : {gt_s.get('hours_fab',0):>4}h fab, "
          f"€{gt_s.get('base_price',0):>6.0f} prix, "
          f"{gt_s.get('nb_components',0):>2} comps, "
          f"{len(gt_s.get('categories', []))} categories")
    print(f"  LLM       : {llm_s.get('hours_fab',0):>4}h fab, "
          f"€{llm_s.get('estimated_price',0):>6.0f} prix, "
          f"{llm_s.get('nb_items',0):>2} items, "
          f"{len(llm_s.get('categories', []))} categories")
    top = r.get("retrieved_top3", [])
    if top:
        print(f"  Top match : [{top[0]['sim']}] {top[0]['id']}")
    if r.get("accessories_matched"):
        print(f"  Acc rules : {', '.join(r['accessories_matched'])}")
    print(f"\n  Scores:")
    for dim in DIMENSIONS:
        s = r["scores"].get(dim)
        if s is None:
            continue
        bar = "★" * s + "☆" * (5 - s)
        print(f"    {DIM_LABELS[dim]:<22} {s}/5  {bar}   {r['details'].get(dim, '')}")
    print(f"\n  OVERALL   : {r['overall']}/5   ({r['elapsed_s']}s)")


def print_aggregate(results: list):
    ok = [r for r in results if "error" not in r]
    if not ok:
        print("\nNo successful runs.")
        return

    print(f"\n\n{'═' * 78}")
    print(f" AGGREGATE REPORT   ({len(ok)}/{len(results)} successful)")
    print('═' * 78)

    # Per-dimension average (Compréhension / RAG / Armoire / BoM / Heures / Prix)
    print(f"\n  {'Dimension':<22} {'Avg':>4}  {'Distribution (1-5)':<24}  Matching feedback avg")
    print(f"  {'-' * 22} {'-' * 4}  {'-' * 24}  {'-' * 22}")
    feedback_baselines = {  # from CETIE Feedback Testeurs.xlsx Synthèse sheet
        "comprehension": 4.5,
        "retrieval":     3.5,
        "enclosure":     3.0,
        "bom":           3.5,
        "hours":         4.5,
        "price":         3.5,
    }
    for dim in DIMENSIONS:
        vals = [r["scores"].get(dim) for r in ok if r["scores"].get(dim) is not None]
        if not vals:
            continue
        avg = mean(vals)
        # Distribution
        dist = [vals.count(i) for i in range(1, 6)]
        bar = "".join(f"{n}" if n > 0 else "·" for n in dist)  # compact
        baseline = feedback_baselines[dim]
        delta = avg - baseline
        arrow = "↑" if delta > 0.1 else ("↓" if delta < -0.1 else "≈")
        print(f"  {DIM_LABELS[dim]:<22} {avg:.2f}  1:{dist[0]} 2:{dist[1]} 3:{dist[2]} 4:{dist[3]} 5:{dist[4]}"
              f"     baseline {baseline:.2f} {arrow}{abs(delta):+.2f}")

    overalls = [r["overall"] for r in ok]
    print(f"\n  {'OVERALL':<22} {mean(overalls):.2f}  (min {min(overalls):.2f}, max {max(overalls):.2f}, median {median(overalls):.2f})")

    # Bottom 3 cases (worst performers — interesting for diagnosis)
    worst = sorted(ok, key=lambda r: r["overall"])[:3]
    print(f"\n  Bottom 3 cases (lowest overall score):")
    for r in worst:
        print(f"    {r['overall']:.2f}  {r['id'][:45]:<45}  {r.get('client','')}")

    # Top 3 cases
    best = sorted(ok, key=lambda r: -r["overall"])[:3]
    print(f"\n  Top 3 cases (highest overall score):")
    for r in best:
        print(f"    {r['overall']:.2f}  {r['id'][:45]:<45}  {r.get('client','')}")


def write_csv(results: list, path: str):
    """Write an Excel-compatible CSV that mirrors the feedback sheet structure."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f, delimiter=";")
        w.writerow(["#", "DEVIS id", "Client", "Year",
                    "Request preview",
                    "GT fab (h)", "LLM fab (h)", "GT price (€)", "LLM price (€)",
                    "Compréhension", "Projets similaires", "Armoire",
                    "BoM composants", "Heures câblage", "Prix matière",
                    "OVERALL /5",
                    "Top retrieved", "Accessories matched", "Elapsed (s)",
                    "Notes"])
        for i, r in enumerate(results, 1):
            if "error" in r:
                w.writerow([i, r.get("id", ""), r.get("client", ""), r.get("year", ""),
                            "", "", "", "", "", "", "", "", "", "", "", "",
                            "", "", r.get("elapsed_s", 0), f"ERROR: {r['error']}"])
                continue
            s = r.get("scores", {})
            gt_s = r.get("gt_summary", {})
            llm_s = r.get("llm_summary", {})
            top = r.get("retrieved_top3", [])
            top_str = f"{top[0]['id']} ({top[0]['sim']})" if top else ""
            w.writerow([i, r.get("id", ""), r.get("client", ""), r.get("year", ""),
                        r.get("request_preview", "")[:200],
                        gt_s.get("hours_fab", ""), llm_s.get("hours_fab", ""),
                        gt_s.get("base_price", ""), llm_s.get("estimated_price", ""),
                        s.get("comprehension", ""), s.get("retrieval", ""),
                        s.get("enclosure", ""), s.get("bom", ""),
                        s.get("hours", ""), s.get("price", ""),
                        r.get("overall", ""),
                        top_str,
                        " | ".join(r.get("accessories_matched", [])),
                        r.get("elapsed_s", ""), ""])
    print(f"\nCSV written to {path}")


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def load_projects(year: str) -> list:
    path = BASE_DIR / "data" / f"yearly_projects_{year}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _request_has_substance(req: str) -> bool:
    """Heuristic: does the client_request actually contain technical content,
    or is it mostly email boilerplate (signature, forwarded headers)?"""
    if not req or len(req) < 120:
        return False
    req_low = req.lower()
    # Must mention at least one technical concept
    tech_signals = ["pompe", "moteur", "armoire", "coffret", "kw", "kva",
                    "amp", "variateur", "automate", "démarreur", "ip", "vdc", "vac"]
    has_tech = sum(1 for s in tech_signals if s in req_low) >= 2
    # Must have at least 15 meaningful words (rough estimate)
    word_count = len(re.findall(r"\b\w{3,}\b", req))
    return has_tech and word_count >= 20


def select_projects(all_projects: list, n: int, seed: int = 42) -> list:
    """Select N non-trivial projects with enough data to score meaningfully."""
    testable = [p for p in all_projects
                if (p.get("configuration", {}).get("nb_components", 0) >= 5
                    and _request_has_substance(p.get("client_request", ""))
                    and p.get("configuration", {}).get("hours_fabrication", 0) >= 4)]
    random.seed(seed)
    random.shuffle(testable)
    return testable[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", action="append", default=None,
                    help="Year(s) to sample from. Default: both 2022 and 2026.")
    ap.add_argument("--n", type=int, default=10,
                    help="Number of projects to test per year (default 10)")
    ap.add_argument("--ids", type=str, default=None,
                    help="Comma-separated DEVIS ids to test (overrides --n)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--quick", action="store_true",
                    help="Skip LLM config generation — only extraction + retrieval")
    ap.add_argument("--no-accessories", action="store_true",
                    help="Disable the accessory rules (for A/B comparison)")
    ap.add_argument("--csv", type=str, default=None, help="Write Excel CSV report")
    ap.add_argument("--json", type=str, default=None, help="Write full JSON report")
    args = ap.parse_args()

    if args.no_accessories:
        # Clear the rules so get_applicable_accessories() returns ""
        app.ACCESSORIES_RULES = []
        print(" [A/B] Accessory rules DISABLED for this run.")

    years = args.year or ["2022", "2026"]

    # Collect test cases
    cases = []
    if args.ids:
        wanted = set(args.ids.split(","))
        for y in years:
            for p in load_projects(y):
                if p.get("id") in wanted or any(w in p.get("id", "") for w in wanted):
                    cases.append((p, y))
    else:
        for y in years:
            projs = load_projects(y)
            for p in select_projects(projs, args.n, seed=args.seed):
                cases.append((p, y))

    if not cases:
        print("No testable projects found.")
        sys.exit(1)

    print(f"{'═' * 78}")
    print(f" CETIE — Ground-Truth Regression Tester")
    print(f" Years: {', '.join(years)}  |  Cases: {len(cases)}  |  "
          f"Quick: {args.quick}")
    print(f" Accessories rules loaded: {len(app.ACCESSORIES_RULES)}")
    print('═' * 78)

    results = []
    t0 = time.time()
    for i, (proj, year) in enumerate(cases, 1):
        print(f"\n[{i}/{len(cases)}]  {proj.get('id', '')[:50]} …")
        try:
            r = run_case(proj, year=year, quick=args.quick)
        except Exception as e:
            import traceback; traceback.print_exc()
            r = {"id": proj.get("id", ""), "year": year,
                 "client": proj.get("client", ""),
                 "error": str(e), "elapsed_s": 0, "scores": {}, "details": {}}
        results.append(r)
        print_case(r)

    print_aggregate(results)

    if args.csv:
        write_csv(results, args.csv)
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\nJSON written to {args.json}")

    total = round(time.time() - t0, 1)
    print(f"\nTotal elapsed: {total}s ({total/max(len(cases),1):.1f}s per case)")


if __name__ == "__main__":
    main()
