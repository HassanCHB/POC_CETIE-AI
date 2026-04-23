#!/usr/bin/env python3
"""
eval_full.py – CETIE AI Configurator — Full production accuracy evaluation
===========================================================================

Tests the EXACT production pipeline on held-out projects, measuring what
actually matters to the client.

WHAT IS TESTED
--------------
  1. Price accuracy        — MAPE, signed bias, error distribution, by price tier
  2. BoM category quality  — Recall, Precision, F1, per-category miss breakdown
  3. Hours accuracy        — Fabrication + programming MAPE + bias
  4. Component quality     — Catalogue match rate (verified / suggested / not_found)
  5. Verified price coverage — % of total estimate backed by real catalogue prices
  6. Retrieval quality     — Does RAG find semantically relevant references?

METHODOLOGY (no data leakage)
------------------------------
  • Strict 80/20 stratified split by product_type.
  • Held-out ChromaDB collection built from TRAIN projects only.
  • Test projects are NEVER in the RAG index or similar-project context.
  • Similar projects fed to the LLM include their FULL BoM data (from train set),
    exactly as in production — not the stripped metadata the old eval used.
  • Uses the exact production prompt + claude-sonnet-4-6 + max_tokens=8000.

IMPROVEMENTS OVER eval_pipeline.py
------------------------------------
  • Production model (sonnet) not haiku — tests what the client actually gets
  • Full BoM data in similar-project context — fixes a major gap in the old eval
  • Catalogue matcher run on every result → real component quality metrics
  • Bias (signed error) — do we over- or under-estimate systematically?
  • Price-tier buckets — accuracy for small / medium / large projects
  • Per-category miss breakdown — which categories are hardest
  • F1 score — balances recall and precision
  • Bootstrap confidence intervals on MAPE
  • Parallel execution (--workers) to speed up n=30+ runs

USAGE
-----
  python3 poc/eval_full.py                        # n=15, full eval
  python3 poc/eval_full.py --n 30                 # more test projects
  python3 poc/eval_full.py --no-llm               # retrieval only (free)
  python3 poc/eval_full.py --n 20 --verbose       # per-project breakdown
  python3 poc/eval_full.py --mode stats           # dataset analysis only
  python3 poc/eval_full.py --workers 3 --n 30     # parallel LLM calls
"""

import os
import sys
import json
import math
import random
import argparse
import time
import datetime
import statistics
import concurrent.futures
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ── Env ────────────────────────────────────────────────────────────────────────
env_path = BASE_DIR / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

import rag
import catalogue_matcher as cm
from json_repair import repair_json

# ── Constants ──────────────────────────────────────────────────────────────────
DATA_PATH    = BASE_DIR / "data" / "yearly_projects_2022.json"
BLOCKS_PATH  = BASE_DIR / "data" / "blocks.json"
ARMOIRES_PATH= BASE_DIR / "data" / "armoires.json"
REPORT_PATH  = BASE_DIR / "data" / "eval_report_full.json"
HOLDOUT_COLL = "yearly_projects_eval_full_train"
YEAR         = "2022"

CHASSIS_SUBS = {
    "04_internal_chassis_power",
    "04_internal_chassis_control",
    "04_internal_chassis_automation",
}

# Price tiers for bucketed analysis
PRICE_TIERS = [
    ("micro",  0,    500,   "< €500  (micro)"),
    ("small",  500,  3000,  "€500–3k (small)"),
    ("medium", 3000, 10000, "€3k–10k (medium)"),
    ("large",  10000, 9e9,  "> €10k  (large)"),
]


# ══════════════════════════════════════════════════════════════════════════════
# Data loading helpers
# ══════════════════════════════════════════════════════════════════════════════

def load_projects() -> list:
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)

def load_blocks() -> tuple[list, list]:
    with open(BLOCKS_PATH, encoding="utf-8") as f:
        blocks = json.load(f)
    with open(ARMOIRES_PATH, encoding="utf-8") as f:
        armoires = json.load(f)
    return blocks, armoires


def project_ground_truth(p: dict) -> dict:
    conf = p.get("configuration", {})
    cats = conf.get("by_category", {})
    raw  = set(c for c, items in cats.items() if items)
    normalised = set()
    for c in raw:
        if c == "04_internal_chassis":
            normalised.update(CHASSIS_SUBS)
        else:
            normalised.add(c)
    scoreable = normalised - {"04_internal_chassis"}
    return {
        "id":                  p["id"],
        "client":              p.get("client", ""),
        "description":         p.get("description", ""),
        "product_type":        p.get("product_type", ""),
        "sector":              p.get("sector", p.get("metier", "")),
        "base_price":          conf.get("base_price", 0),
        "hours_fabrication":   conf.get("hours_fabrication", 0),
        "hours_programmation": conf.get("hours_programmation", 0),
        "nb_components":       conf.get("nb_components", 0),
        "categories_present":  sorted(scoreable),
        "client_request":      p.get("client_request", ""),
    }


def _pct_error(predicted, actual) -> Optional[float]:
    if not actual:
        return None
    return abs(predicted - actual) / abs(actual) * 100

def _signed_pct_error(predicted, actual) -> Optional[float]:
    """Positive = overestimate, negative = underestimate."""
    if not actual:
        return None
    return (predicted - actual) / abs(actual) * 100

def bar(v: float, width: int = 20, char: str = "█") -> str:
    v = max(0.0, min(1.0, float(v)))
    filled = round(v * width)
    return char * filled + "░" * (width - filled)

def _bootstrap_ci(values: list, n: int = 1000, ci: float = 0.95) -> tuple[float, float]:
    """Bootstrap confidence interval for the mean."""
    if len(values) < 2:
        return (values[0], values[0]) if values else (0.0, 0.0)
    samples = []
    for _ in range(n):
        s = [random.choice(values) for _ in values]
        samples.append(statistics.mean(s))
    samples.sort()
    lo = int((1 - ci) / 2 * n)
    hi = int((1 + ci) / 2 * n)
    return round(samples[lo], 1), round(samples[hi], 1)


# ══════════════════════════════════════════════════════════════════════════════
# Held-out index management  (same as eval_pipeline.py)
# ══════════════════════════════════════════════════════════════════════════════

def _project_to_text(p: dict) -> str:
    parts = [
        p.get("client_request", ""),
        p.get("description", ""),
        p.get("product_type", ""),
        p.get("client", ""),
        p.get("metier", ""),
        " ".join(p.get("tags", [])),
        " ".join(p.get("configuration", {}).get("key_components", [])[:5]),
    ]
    return " ".join(x for x in parts if x).strip()


def build_holdout_index(train_projects: list) -> None:
    print(f"  Building temporary train index ({len(train_projects)} projects) …")
    oai    = rag._openai_client()
    chroma = rag._chroma_client()
    try:
        chroma.delete_collection(HOLDOUT_COLL)
    except Exception:
        pass
    collection = chroma.create_collection(HOLDOUT_COLL, metadata={"hnsw:space": "cosine"})
    ids, embeddings, documents, metadatas = [], [], [], []
    for idx, p in enumerate(train_projects):
        text = _project_to_text(p)
        if not text.strip():
            continue
        conf = p.get("configuration", {})
        ids.append(f"{p['id']}_{idx}")
        embeddings.append(rag.embed_text(text, oai))
        documents.append(text)
        metadatas.append({
            "id":           str(p["id"]),
            "product_type": p.get("product_type", ""),
            "sector":       p.get("sector", p.get("metier", "")),
            "client":       p.get("client", ""),
            "base_price":   str(conf.get("base_price", 0)),
        })
    collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    print(f"  Train index ready — {len(ids)} projects embedded.")


def query_holdout_index(query_text: str, n_results: int = 5) -> list:
    chroma     = rag._chroma_client()
    collection = chroma.get_collection(HOLDOUT_COLL)
    oai        = rag._openai_client()
    query_vec  = rag.embed_text(query_text, oai)
    results    = collection.query(
        query_embeddings=[query_vec],
        n_results=min(n_results, collection.count()),
        include=["metadatas", "distances"],
    )
    similar = []
    for i, uid in enumerate(results["ids"][0]):
        meta  = results["metadatas"][0][i]
        score = round(1.0 - results["distances"][0][i], 3)
        similar.append({
            "id":               meta.get("id", uid),
            "product_type":     meta.get("product_type", ""),
            "sector":           meta.get("sector", ""),
            "client":           meta.get("client", ""),
            "base_price":       float(meta.get("base_price", 0)),
            "similarity_score": score,
        })
    return similar


def teardown_holdout_index() -> None:
    try:
        rag._chroma_client().delete_collection(HOLDOUT_COLL)
        print("  Temporary train index removed.")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Train / Test split
# ══════════════════════════════════════════════════════════════════════════════

def split_train_test(projects: list, test_ratio: float = 0.20, seed: int = 42):
    random.seed(seed)
    groups = {}
    for p in projects:
        groups.setdefault(p.get("product_type", "unknown"), []).append(p)
    train, test = [], []
    for _, members in groups.items():
        random.shuffle(members)
        n_test = max(1, round(len(members) * test_ratio)) if len(members) >= 3 else 0
        test.extend(members[:n_test])
        train.extend(members[n_test:])
    random.shuffle(test)
    return train, test


# ══════════════════════════════════════════════════════════════════════════════
# Production pipeline call  (mirrors app.py streaming endpoint exactly)
# ══════════════════════════════════════════════════════════════════════════════

def _search_blocks(keywords: list, all_blocks: list, all_armoires: list, max_results: int = 50) -> list:
    results = []
    keywords_lower = [k.lower() for k in keywords if k]
    seen_ids = set()
    for block in all_blocks + all_armoires:
        if block["id"] in seen_ids:
            continue
        text  = f"{block['categorie']} {block['designation']} {block['label']}".lower()
        score = sum(1 for kw in keywords_lower if kw in text)
        if score > 0:
            results.append((score, block))
            seen_ids.add(block["id"])
    results.sort(key=lambda x: -x[0])
    return [b for _, b in results[:max_results]]


def _enrich_blocks_from_quotes(matching_blocks: list, similar_quotes: list,
                                all_blocks: list, all_armoires: list) -> list:
    all_by_id    = {b["id"]: b for b in all_blocks + all_armoires}
    existing_ids = {b["id"] for b in matching_blocks}
    enriched     = list(matching_blocks)
    for q in similar_quotes:
        for sb in q.get("selected_blocks", []):
            bid = sb.get("id")
            if bid and bid not in existing_ids:
                full = all_by_id.get(bid)
                if full:
                    enriched.append(full)
                    existing_ids.add(bid)
    return enriched


def _build_project_context(proj: dict) -> str:
    """Build the detailed BoM context for a real DEVIS project (production format)."""
    conf      = proj.get("configuration", {})
    cats      = conf.get("by_category", {})
    bom_lines = []
    for cat_code, items in cats.items():
        if items:
            item_desgs = [f"{it.get('quantity',1)}x {it.get('designation','')}" for it in items[:4]]
            bom_lines.append(f"  {cat_code}: {', '.join(item_desgs)}")
    bom_str = "\n".join(bom_lines) if bom_lines else "  (no items)"
    return (
        f"Client: {proj.get('client','')} | Description: {proj.get('description','')}\n"
        f"Fabrication: {conf.get('hours_fabrication',0)}h | Prog: {conf.get('hours_programmation',0)}h | "
        f"Prix devis: {conf.get('base_price',0):.0f}€\n"
        f"BoM:\n{bom_str}"
    )


def _call_production_llm(
    client_request: str,
    similar_quotes: list,
    similar_projects_full: list,   # FULL project dicts from train set
    all_blocks: list,
    all_armoires: list,
    api_key: str,
) -> tuple[dict, float]:
    """
    Run the EXACT same config generation as app.py streaming endpoint.
    Returns (configuration_dict, elapsed_seconds).
    """
    import anthropic, re as _re, json as _json

    # Step 1 — extract requirements (haiku, cheap)
    client_h = anthropic.Anthropic(api_key=api_key)
    ext_prompt = f"""Expert CETIE. Extract requirements from this customer request.
Respond ONLY with JSON.

<request>{client_request}</request>

{{
  "product_type": "brief type",
  "power_kw": null,
  "nb_pumps": null,
  "nb_motors": null,
  "voltage": null,
  "protection_ip": null,
  "automation": null,
  "communication": null,
  "keywords": ["french", "keywords"],
  "summary": "1 sentence"
}}"""
    ext_resp = client_h.messages.create(
        model="claude-haiku-4-5", max_tokens=600,
        messages=[{"role": "user", "content": ext_prompt}]
    )
    try:
        raw_ext = ext_resp.content[0].text
        m = _re.search(r'\{.*\}', raw_ext, _re.DOTALL)
        requirements = _json.loads(m.group()) if m else {}
    except Exception:
        requirements = {"keywords": [], "summary": client_request[:100]}

    # Step 2 — search blocks
    keywords = requirements.get("keywords", [])
    if requirements.get("product_type"):
        keywords += requirements["product_type"].lower().split()
    if requirements.get("automation"):
        keywords += requirements["automation"].lower().split()

    matching_blocks = _search_blocks(keywords, all_blocks, all_armoires, max_results=50)
    matching_blocks = _enrich_blocks_from_quotes(matching_blocks, similar_quotes,
                                                  all_blocks, all_armoires)

    blocks_text = "\n".join(
        f"[{b['id']}] {b['categorie']} | {b['designation']} | {b['heures_cablage']}h | €{b['cout']:.2f}"
        for b in matching_blocks
    )

    # Step 3 — build context from similar DEVIS (with full BoM — key improvement)
    yearly_section = ""
    if similar_projects_full:
        proj_parts = []
        seen_cats  = set()
        for i, proj in enumerate(similar_projects_full[:3]):
            score = proj.get("_similarity_score", 0)
            proj_parts.append(
                f"--- Real DEVIS #{i+1} (similarity: {score:.0%}) ---\n"
                + _build_project_context(proj)
            )
            for cat, items in proj.get("configuration", {}).get("by_category", {}).items():
                if items:
                    seen_cats.add(cat)
        yearly_section = (
            "\n=== Real CETIE DEVIS projects — use as primary BoM reference ===\n"
            + "\n\n".join(proj_parts) + "\n"
        )
        # Category hint
        seen_cats.discard("04_internal_chassis")
        if any(c.startswith("04_internal") for c in seen_cats):
            seen_cats.add("04_internal_chassis_power")
        cat_hint = (
            f"\nIMPORTANT — Similar DEVIS used: {', '.join(sorted(seen_cats))}. "
            f"Populate ALL of them.\n"
        ) if seen_cats else ""
    else:
        cat_hint = ""

    # Step 4 — RAG quotes context
    if similar_quotes:
        rag_context = "\n\n".join(
            f"--- Quote #{i+1} ({q.get('similarity_score',0):.0%}) ---\n"
            f"Type: {q.get('product_type','')} | "
            f"Hours: {q.get('configuration',{}).get('total_hours_cablage','?')}h wiring"
            for i, q in enumerate(similar_quotes)
        )
        rag_section = f"\n=== Historical CETIE quotes ===\n{rag_context}\n"
    else:
        rag_section = ""

    # Step 5 — build the EXACT config prompt (same template as app.py)
    config_prompt = f"""You are a CETIE technical expert configuring electrical control panels.

Customer request: {client_request}

Extracted requirements:
{_json.dumps(requirements, ensure_ascii=False, indent=2)}
{yearly_section}{rag_section}
Available blocks (ID | Category | Designation | Wiring hours | Cost):
{blocks_text}

Available enclosures:
{chr(10).join(f"[{a['id']}] {a['categorie']} | {a['designation']} | {a['heures_cablage']}h | €{a['cout']:.2f}" for a in all_armoires[:30])}

{cat_hint}
MANDATORY BoM category rules:
- 01_cabinet_enclosure: ALWAYS populate.
- 04_internal_chassis_power: ALWAYS for motor/pump projects.
- 06_door_controls: ALWAYS populate.
- 11_labor: ALWAYS — wiring + programming hours separately.
- Leave [] ONLY if genuinely does not apply.

CRITICAL JSON RULES:
1. Respond with ONLY the JSON object.
2. Every string value must be on ONE line.
3. Use decimal DOT never comma for numbers.

{{
  "enclosure": {{"id": null, "designation": "", "justification": ""}},
  "blocks": [],
  "bom_categories": {{
    "01_cabinet_enclosure":           [{{"designation": "", "quantity": 1, "unit_price": 0}}],
    "02_equipment_on_side":           [],
    "04_internal_chassis_power":      [],
    "04_internal_chassis_control":    [],
    "04_internal_chassis_automation": [],
    "05_equipment_on_top":            [],
    "06_door_controls":               [],
    "07_supplied_separately":         [],
    "09_commissioning":               [],
    "10_packaging":                   [],
    "11_labor":                       [{{"designation": "Main d'oeuvre câblage", "quantity": 1, "hours": 0, "hourly_rate": 65}}, {{"designation": "Main d'oeuvre programmation", "quantity": 1, "hours": 0, "hourly_rate": 75}}],
    "12_options":                     []
  }},
  "total_hours_cablage": 0,
  "total_hours_prog": 0,
  "estimated_material_cost": 0,
  "estimated_price": 0,
  "spare_reserve_pct": 20,
  "missing_info": [],
  "assumptions": [],
  "expert_notes": ""
}}

Fill bom_categories with actual items from the blocks list. Mirror the similar DEVIS structure above.
For spare_reserve_pct: 15=simple, 20=standard, 25-30=complex."""

    # Step 6 — call production model
    client_s = anthropic.Anthropic(api_key=api_key)
    t0 = time.time()
    resp = client_s.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": config_prompt}]
    )
    elapsed = time.time() - t0

    raw = resp.content[0].text
    stop_reason = resp.stop_reason
    if stop_reason == "max_tokens":
        print(f"    ⚠ Response truncated (stop_reason=max_tokens, len={len(raw)})")

    # Step 7 — parse JSON
    try:
        m = _re.search(r'\{.*\}', raw, _re.DOTALL)
        cfg = _json.loads(m.group()) if m else {}
    except Exception:
        try:
            cfg = repair_json(raw, return_objects=True)
            if not isinstance(cfg, dict):
                cfg = {}
        except Exception:
            cfg = {"_parse_error": raw[:300]}

    # Step 8 — run catalogue matcher
    if "bom_categories" in cfg and isinstance(cfg["bom_categories"], dict):
        cfg["bom_categories"] = cm.match_bom_categories(cfg["bom_categories"])

    return cfg, elapsed


# ══════════════════════════════════════════════════════════════════════════════
# Metrics helpers
# ══════════════════════════════════════════════════════════════════════════════

def _catalogue_stats(bom_categories: dict) -> dict:
    """
    Analyse catalogue match quality across all BoM items.
    Returns counts + rates for verified / suggested / not_found / skipped.
    """
    total = verified = suggested = not_found = skipped = 0
    verified_price_sum = 0.0
    total_price_sum    = 0.0

    for cat_key, items in bom_categories.items():
        if cat_key == "_match_stats" or not isinstance(items, list):
            continue
        for it in items:
            status = it.get("match_status", "not_found")
            price  = float(it.get("unit_price", 0) or 0)
            qty    = int(it.get("quantity", 1) or 1)
            line   = price * qty

            if status == "skipped":
                skipped += 1
                continue
            total      += 1
            total_price_sum += line
            if status == "verified":
                verified += 1
                verified_price_sum += line
            elif status == "suggested":
                suggested += 1
                verified_price_sum += line * 0.5   # partial credit
            elif status == "not_found":
                not_found += 1

    match_rate = (verified + suggested) / total if total else 0
    price_cov  = verified_price_sum / total_price_sum if total_price_sum else 0
    return {
        "total_items":     total,
        "verified":        verified,
        "suggested":       suggested,
        "not_found":       not_found,
        "skipped":         skipped,
        "match_rate":      round(match_rate, 3),
        "verified_price_coverage": round(price_cov, 3),
    }


def _get_tier(price: float) -> str:
    for name, lo, hi, _ in PRICE_TIERS:
        if lo <= price < hi:
            return name
    return "large"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — Retrieval quality  (same as before, included for completeness)
# ══════════════════════════════════════════════════════════════════════════════

def eval_retrieval(test_projects: list, train_projects: list, verbose: bool = False) -> dict:
    print(f"\n{'─'*60}")
    print("TEST 1 — Held-out Retrieval Quality")
    print(f"  Train: {len(train_projects)}  |  Test: {len(test_projects)}")
    print(f"{'─'*60}")

    testable = [p for p in test_projects if len(p.get("client_request", "")) > 40]
    k_values  = (1, 3, 5)
    pt_hits   = {k: 0 for k in k_values}
    sec_hits  = {k: 0 for k in k_values}
    top1_scores = []
    total = 0

    for p in testable:
        gt      = project_ground_truth(p)
        results = query_holdout_index(gt["client_request"][:500], n_results=5)
        if not results:
            continue
        top1_scores.append(results[0]["similarity_score"])
        ret_types   = [r["product_type"] for r in results]
        ret_sectors = [r["sector"]        for r in results]
        for k in k_values:
            if gt["product_type"] in ret_types[:k]:   pt_hits[k]  += 1
            if gt["sector"]       in ret_sectors[:k]:  sec_hits[k] += 1
        total += 1
        if verbose:
            m = "✓" if gt["product_type"] == results[0]["product_type"] else "✗"
            print(f"  {gt['id']:<22} [{gt['product_type'][:28]:<28}] "
                  f"→ {m} {results[0]['product_type'][:28]:<28} {results[0]['similarity_score']:.3f}")

    avg_top1 = statistics.mean(top1_scores) if top1_scores else 0
    pt_match  = {k: pt_hits[k]  / total if total else 0 for k in k_values}
    sec_match = {k: sec_hits[k] / total if total else 0 for k in k_values}

    print(f"\n  Projects queried : {total}")
    print(f"  Avg top-1 sim    : {avg_top1:.3f}")
    print()
    for k in k_values:
        print(f"  Product-type match@{k} : {pt_match[k]:.0%}  {bar(pt_match[k])}")
    print()
    for k in k_values:
        print(f"  Sector match@{k}       : {sec_match[k]:.0%}  {bar(sec_match[k])}")

    return {
        "total": total, "avg_top1_sim": round(avg_top1, 3),
        "product_type_match": {str(k): round(v, 3) for k, v in pt_match.items()},
        "sector_match":       {str(k): round(v, 3) for k, v in sec_match.items()},
    }


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — Full production LLM accuracy
# ══════════════════════════════════════════════════════════════════════════════

def _eval_one_project(args_tuple) -> dict:
    """Worker function — evaluates a single test project. Used for parallel execution."""
    (p, train_by_id, all_blocks, all_armoires, api_key, verbose) = args_tuple

    gt  = project_ground_truth(p)
    pid = gt["id"]

    query   = gt["client_request"][:500]
    sim_q   = rag.retrieve_similar(query, n_results=3)
    sim_p   = query_holdout_index(query, n_results=5)

    # KEY IMPROVEMENT: enrich retrieved projects with full BoM from train set
    sim_p_full = []
    for r in sim_p:
        full = train_by_id.get(str(r["id"]))
        if full:
            full_copy = dict(full)
            full_copy["_similarity_score"] = r["similarity_score"]
            sim_p_full.append(full_copy)
        else:
            sim_p_full.append({
                "id": r["id"], "client": r["client"], "description": r["product_type"],
                "product_type": r["product_type"], "_similarity_score": r["similarity_score"],
                "configuration": {"base_price": r["base_price"], "hours_fabrication": 0,
                                  "hours_programmation": 0, "by_category": {}},
            })

    try:
        cfg, elapsed = _call_production_llm(
            gt["client_request"], sim_q, sim_p_full, all_blocks, all_armoires, api_key
        )
    except Exception as e:
        print(f"    [{pid}] LLM ERROR: {e}")
        return {"id": pid, "error": str(e), "gt": gt}

    if "_parse_error" in cfg:
        print(f"    [{pid}] JSON PARSE ERROR")
        return {"id": pid, "error": "json_parse", "gt": gt}

    # ── Category metrics ─────────────────────────────────────────────────────
    scoreable_gt = set(gt["categories_present"])
    llm_cats     = set(
        k for k, v in cfg.get("bom_categories", {}).items()
        if k != "_match_stats" and isinstance(v, list) and len(v) > 0
    )
    tp       = scoreable_gt & llm_cats
    recall   = len(tp) / len(scoreable_gt) if scoreable_gt else 1.0
    prec     = len(tp) / len(llm_cats)     if llm_cats    else 0.0
    f1       = 2 * prec * recall / (prec + recall) if (prec + recall) > 0 else 0.0

    # ── Price metrics ─────────────────────────────────────────────────────────
    llm_price  = float(cfg.get("estimated_price", 0) or 0)
    gt_price   = gt["base_price"]
    price_err  = _pct_error(llm_price, gt_price)
    price_bias = _signed_pct_error(llm_price, gt_price)

    # ── Hours metrics ─────────────────────────────────────────────────────────
    llm_fab  = float(cfg.get("total_hours_cablage", 0) or cfg.get("hours_fabrication", 0) or 0)
    llm_prog = float(cfg.get("total_hours_prog", 0)    or cfg.get("hours_programmation", 0) or 0)
    fab_err  = _pct_error(llm_fab,  gt["hours_fabrication"])
    prog_err = _pct_error(llm_prog, gt["hours_programmation"])
    fab_bias = _signed_pct_error(llm_fab,  gt["hours_fabrication"])
    prog_bias= _signed_pct_error(llm_prog, gt["hours_programmation"])

    # ── Catalogue quality ─────────────────────────────────────────────────────
    cat_stats = _catalogue_stats(cfg.get("bom_categories", {}))

    row = {
        "id":               pid,
        "description":      gt["description"],
        "product_type":     gt["product_type"],
        "price_tier":       _get_tier(gt_price),
        "gt_price":         gt_price,
        "llm_price":        llm_price,
        "price_err_pct":    round(price_err, 1)  if price_err  is not None else None,
        "price_bias_pct":   round(price_bias, 1) if price_bias is not None else None,
        "gt_hours_fab":     gt["hours_fabrication"],
        "llm_hours_fab":    llm_fab,
        "fab_err_pct":      round(fab_err, 1)   if fab_err  is not None else None,
        "fab_bias_pct":     round(fab_bias, 1)  if fab_bias is not None else None,
        "gt_hours_prog":    gt["hours_programmation"],
        "llm_hours_prog":   llm_prog,
        "prog_err_pct":     round(prog_err, 1)  if prog_err is not None else None,
        "prog_bias_pct":    round(prog_bias, 1) if prog_bias is not None else None,
        "gt_categories":    sorted(scoreable_gt),
        "llm_categories":   sorted(llm_cats),
        "missed_categories": sorted(scoreable_gt - llm_cats),
        "extra_categories":  sorted(llm_cats - scoreable_gt),
        "category_recall":   round(recall, 3),
        "category_precision":round(prec, 3),
        "category_f1":       round(f1, 3),
        "catalogue_stats":   cat_stats,
        "micro_project":     gt_price < 500,
        "top1_ref":          sim_p[0]["id"] if sim_p else None,
        "top1_score":        sim_p[0]["similarity_score"] if sim_p else 0,
        "llm_elapsed_s":     round(elapsed, 1),
        "stop_reason":       cfg.get("_stop_reason", ""),
    }

    if verbose:
        over = "↑" if (price_bias or 0) > 0 else "↓"
        print(f"    GT:  €{gt_price:>7.0f}  |  LLM: €{llm_price:>7.0f}"
              + (f"  err={price_err:.0f}% {over}" if price_err is not None else "  N/A"))
        print(f"    Fab: {gt['hours_fabrication']:>5.0f}h  |  LLM: {llm_fab:>5.0f}h"
              + (f"  err={fab_err:.0f}%" if fab_err is not None else ""))
        print(f"    Cat recall={recall:.0%}  prec={prec:.0%}  F1={f1:.0%}"
              + (f"  missed={sorted(scoreable_gt-llm_cats)}" if scoreable_gt-llm_cats else "  ✓ all"))
        print(f"    Catalogue: {cat_stats['verified']}✓ {cat_stats['suggested']}~ {cat_stats['not_found']}?  "
              f"match_rate={cat_stats['match_rate']:.0%}  price_cov={cat_stats['verified_price_coverage']:.0%}")
    return row


def eval_llm_accuracy(test_projects: list, train_by_id: dict,
                      all_blocks: list, all_armoires: list,
                      n: int = 15, verbose: bool = False, workers: int = 1) -> dict:
    print(f"\n{'─'*60}")
    print(f"TEST 2 — Production LLM Accuracy  (n={n})")
    print(f"  Model: claude-sonnet-4-6 | max_tokens=8000 | workers={workers}")
    print(f"  Test projects are NEVER in RAG context.")
    print(f"  Similar-project context includes FULL BoM data from train set.")
    print(f"{'─'*60}")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    candidates = [
        p for p in test_projects
        if len(p.get("client_request", "")) > 80
        and p.get("configuration", {}).get("base_price", 0) > 0
    ]
    random.shuffle(candidates)
    subset = candidates[:n]

    if not subset:
        print("  [WARN] No testable projects in test set.")
        return {}

    print(f"  Running {len(subset)} test projects…\n")
    results = []
    args_list = [
        (p, train_by_id, all_blocks, all_armoires, api_key, verbose)
        for p in subset
    ]

    if workers > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_eval_one_project, a): i for i, a in enumerate(args_list)}
            for fut in concurrent.futures.as_completed(futures):
                i   = futures[fut]
                row = fut.result()
                results.append(row)
                pid = row.get("id", "?")
                done = len(results)
                print(f"  [{done}/{len(subset)}] {pid}" +
                      (f" — error: {row['error']}" if "error" in row
                       else f"  price_err={row.get('price_err_pct','N/A')}%"
                            f"  F1={row.get('category_f1','?'):.0%}"))
    else:
        for i, args in enumerate(args_list):
            pid = args[0]["id"]
            print(f"\n  [{i+1}/{len(subset)}] {pid} — {args[0].get('description','')[:50]}")
            row = _eval_one_project(args)
            results.append(row)

    # ── Aggregate ─────────────────────────────────────────────────────────────
    ok = [r for r in results if "error" not in r]
    evaluable = [r for r in ok if not r.get("micro_project") and r.get("gt_price", 0) >= 500]

    price_errors  = [r["price_err_pct"]  for r in evaluable if r.get("price_err_pct") is not None]
    price_biases  = [r["price_bias_pct"] for r in evaluable if r.get("price_bias_pct") is not None]
    fab_errors    = [r["fab_err_pct"]    for r in evaluable if r.get("fab_err_pct") is not None and r.get("gt_hours_fab", 0) > 0]
    fab_biases    = [r["fab_bias_pct"]   for r in evaluable if r.get("fab_bias_pct") is not None and r.get("gt_hours_fab", 0) > 0]
    prog_errors   = [r["prog_err_pct"]   for r in evaluable if r.get("prog_err_pct") is not None and r.get("gt_hours_prog", 0) > 0]
    recalls       = [r["category_recall"]    for r in ok]
    precisions    = [r["category_precision"] for r in ok]
    f1s           = [r["category_f1"]        for r in ok]

    cat_match_rates   = [r["catalogue_stats"]["match_rate"]                for r in ok]
    price_cov_rates   = [r["catalogue_stats"]["verified_price_coverage"]   for r in ok]

    # Category miss frequency
    cat_miss_count = {}
    for r in ok:
        for cat in r.get("missed_categories", []):
            cat_miss_count[cat] = cat_miss_count.get(cat, 0) + 1
    cat_miss_rate = {k: round(v / len(ok), 2) for k, v in
                     sorted(cat_miss_count.items(), key=lambda x: -x[1])}

    # Tier breakdown
    tier_results = {}
    for name, lo, hi, label in PRICE_TIERS:
        tier_rows = [r for r in ok if r.get("price_tier") == name and r.get("price_err_pct") is not None]
        if tier_rows:
            errs = [r["price_err_pct"] for r in tier_rows]
            tier_results[name] = {
                "label": label, "n": len(errs),
                "mean_mape": round(statistics.mean(errs), 1),
                "median_mape": round(statistics.median(errs), 1),
            }

    # Product-type breakdown
    type_results = {}
    for r in ok:
        pt = r.get("product_type", "unknown")
        type_results.setdefault(pt, []).append(r.get("price_err_pct"))
    type_mape = {
        pt: round(statistics.mean([e for e in errs if e is not None]), 1)
        for pt, errs in type_results.items()
        if any(e is not None for e in errs)
    }

    summary = {
        "n_tested":  len(subset),
        "n_ok":      len(ok),
        "n_evaluable": len(evaluable),
        # Category
        "mean_category_recall":    round(statistics.mean(recalls),    3) if recalls    else None,
        "mean_category_precision": round(statistics.mean(precisions),  3) if precisions else None,
        "mean_category_f1":        round(statistics.mean(f1s),         3) if f1s        else None,
        "category_miss_rate":      cat_miss_rate,
        # Price
        "mean_price_mape":         round(statistics.mean(price_errors), 1) if price_errors else None,
        "median_price_mape":       round(statistics.median(price_errors), 1) if price_errors else None,
        "price_mape_ci95":         _bootstrap_ci(price_errors) if len(price_errors) >= 2 else None,
        "mean_price_bias":         round(statistics.mean(price_biases), 1) if price_biases else None,
        "price_tier_breakdown":    tier_results,
        "price_by_product_type":   type_mape,
        # Hours
        "mean_fab_mape":           round(statistics.mean(fab_errors), 1) if fab_errors else None,
        "median_fab_mape":         round(statistics.median(fab_errors), 1) if fab_errors else None,
        "mean_fab_bias":           round(statistics.mean(fab_biases), 1) if fab_biases else None,
        "mean_prog_mape":          round(statistics.mean(prog_errors), 1) if prog_errors else None,
        # Catalogue
        "mean_catalogue_match_rate":        round(statistics.mean(cat_match_rates),  3) if cat_match_rates  else None,
        "mean_verified_price_coverage":     round(statistics.mean(price_cov_rates),  3) if price_cov_rates  else None,
        "results": results,
    }

    _print_llm_summary(summary)
    return summary


def _print_llm_summary(s: dict) -> None:
    ok   = s["n_ok"]
    tot  = s["n_tested"]
    ev   = s["n_evaluable"]
    cr   = s.get("mean_category_recall")    or 0
    cp   = s.get("mean_category_precision") or 0
    cf1  = s.get("mean_category_f1")        or 0
    pm   = s.get("mean_price_mape")
    pmd  = s.get("median_price_mape")
    pci  = s.get("price_mape_ci95")
    pb   = s.get("mean_price_bias")
    fm   = s.get("mean_fab_mape")
    fmd  = s.get("median_fab_mape")
    fbi  = s.get("mean_fab_bias")
    pgm  = s.get("mean_prog_mape")
    cmr  = s.get("mean_catalogue_match_rate")  or 0
    pcv  = s.get("mean_verified_price_coverage") or 0

    print(f"\n  ┌{'─'*58}┐")
    print(f"  │  FULL EVAL SUMMARY  ({ok}/{tot} ok | {ev} evaluable)         │")
    print(f"  │  Production model: claude-sonnet-4-6                    │")
    print(f"  ├{'─'*58}┤")
    print(f"  │  BoM CATEGORY QUALITY                                   │")
    print(f"  │    Recall    : {cr:.0%}  {bar(cr)}")
    print(f"  │    Precision : {cp:.0%}  {bar(cp)}")
    print(f"  │    F1 score  : {cf1:.0%}  {bar(cf1)}")
    miss = s.get("category_miss_rate", {})
    if miss:
        top_miss = list(miss.items())[:3]
        print(f"  │    Most missed: {', '.join(f'{k} ({v:.0%})' for k,v in top_miss)}")
    print(f"  ├{'─'*58}┤")
    print(f"  │  PRICE ACCURACY  ({ev} projects ≥ €500)                  │")
    if pm is not None:
        bias_arrow = "↑ overestimates" if (pb or 0) > 5 else ("↓ underestimates" if (pb or 0) < -5 else "≈ unbiased")
        ci_str = f"  CI95=[{pci[0]:.0f}%–{pci[1]:.0f}%]" if pci else ""
        print(f"  │    MAPE mean   : {pm:.1f}%{ci_str}")
        print(f"  │    MAPE median : {pmd:.1f}%")
        print(f"  │    Bias        : {pb:+.1f}%  ({bias_arrow})")
    else:
        print(f"  │    Price MAPE  : N/A")

    tier = s.get("price_tier_breakdown", {})
    if tier:
        print(f"  │    By tier:")
        for _, lo, hi, label in PRICE_TIERS:
            name = [n for n,l,h,_ in PRICE_TIERS if l==lo and h==hi][0]
            if name in tier:
                t = tier[name]
                print(f"  │      {label:<22} n={t['n']}  MAPE={t['mean_mape']:.0f}% (med {t['median_mape']:.0f}%)")
    print(f"  ├{'─'*58}┤")
    print(f"  │  HOURS ACCURACY                                         │")
    if fm is not None:
        fab_bias_arrow = "↑" if (fbi or 0) > 5 else ("↓" if (fbi or 0) < -5 else "≈")
        print(f"  │    Fabrication MAPE   : {fm:.1f}% (med {fmd:.1f}%)  bias={fbi:+.1f}% {fab_bias_arrow}")
    else:
        print(f"  │    Fabrication MAPE   : N/A")
    print(f"  │    Programming MAPE   : {pgm:.1f}%" if pgm else "  │    Programming MAPE   : N/A")
    print(f"  ├{'─'*58}┤")
    print(f"  │  COMPONENT QUALITY                                      │")
    print(f"  │    Catalogue match rate  : {cmr:.0%}  {bar(cmr)}")
    print(f"  │    Verified price cov.   : {pcv:.0%}  {bar(pcv)}")
    print(f"  │    (% of estimate backed by real catalogue prices)      │")
    pt_mape = s.get("price_by_product_type", {})
    if pt_mape:
        print(f"  ├{'─'*58}┤")
        print(f"  │  PRICE MAPE BY PRODUCT TYPE                             │")
        for pt, mape in sorted(pt_mape.items(), key=lambda x: x[1]):
            print(f"  │    {pt[:38]:<38} {mape:>5.0f}%")
    print(f"  └{'─'*58}┘")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — Dataset stats
# ══════════════════════════════════════════════════════════════════════════════

def eval_dataset_stats(projects: list) -> dict:
    print(f"\n{'─'*60}")
    print("Dataset Stats")
    print(f"{'─'*60}")
    total     = len(projects)
    w_request = sum(1 for p in projects if len(p.get("client_request", "")) > 40)
    w_price   = sum(1 for p in projects if p.get("configuration", {}).get("base_price", 0) > 0)
    w_hours   = sum(1 for p in projects if p.get("configuration", {}).get("hours_fabrication", 0) > 0)
    avg_price = statistics.mean(p.get("configuration", {}).get("base_price", 0) for p in projects)
    avg_fab   = statistics.mean(p.get("configuration", {}).get("hours_fabrication", 0) for p in projects)
    prices    = [p.get("configuration", {}).get("base_price", 0) for p in projects if p.get("configuration", {}).get("base_price", 0) > 0]

    cat_counts = {}
    for p in projects:
        for cat, items in p.get("configuration", {}).get("by_category", {}).items():
            if items:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print(f"  Total    : {total}  |  With request: {w_request} ({w_request/total:.0%})"
          f"  |  With price: {w_price} ({w_price/total:.0%})"
          f"  |  With hours: {w_hours} ({w_hours/total:.0%})")
    print(f"  Price    : mean €{avg_price:.0f}  |  median €{statistics.median(prices):.0f}"
          f"  |  range €{min(prices):.0f}–€{max(prices):.0f}")
    print(f"  Fab hrs  : mean {avg_fab:.1f}h  |  Clients: {len(set(p.get('client','') for p in projects))}")

    # Tier distribution
    print(f"\n  Price tier distribution:")
    for name, lo, hi, label in PRICE_TIERS:
        n = sum(1 for p in prices if lo <= p < hi)
        print(f"    {label:<26} {n:>3} ({n/total:.0%})  {bar(n/total, 12)}")

    print(f"\n  BoM category frequency:")
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f"    {cat:<42} {cnt:>3} ({cnt/total:.0%})  {bar(cnt/total, 12)}")

    return {"total": total, "avg_price": round(avg_price), "category_distribution": cat_counts}


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="CETIE — Full production accuracy evaluation")
    parser.add_argument("--mode",    choices=["full", "stats", "retrieval-only"],
                        default="full")
    parser.add_argument("--n",       type=int, default=15,
                        help="LLM test projects (default 15, use 30+ for stable estimates)")
    parser.add_argument("--seed",    type=int, default=42)
    parser.add_argument("--verbose", action="store_true",
                        help="Print per-project breakdown")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel LLM workers (default 1 — set 2-3 for speed)")
    parser.add_argument("--no-llm",  action="store_true",
                        help="Skip LLM calls, only run retrieval test")
    parser.add_argument("--report",  default=str(REPORT_PATH))
    args = parser.parse_args()

    random.seed(args.seed)

    print("=" * 62)
    print("CETIE AI — Full Production Accuracy Evaluation")
    print(f"Date    : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode    : {args.mode}  |  n={args.n}  |  seed={args.seed}  |  workers={args.workers}")
    print(f"Model   : claude-sonnet-4-6  (production model)")
    print(f"Context : full BoM data from train set in similar-project context")
    print("=" * 62)

    if not DATA_PATH.exists():
        print(f"[ERROR] {DATA_PATH} not found")
        sys.exit(1)

    projects  = load_projects()
    all_blocks, all_armoires = load_blocks()
    print(f"\nLoaded {len(projects)} projects | {len(all_blocks)} blocks | {len(all_armoires)} armoires")

    report = {
        "generated_at": datetime.datetime.now().isoformat(),
        "mode":         args.mode,
        "seed":         args.seed,
        "n":            args.n,
        "model":        "claude-sonnet-4-6",
        "methodology":  "held-out 80/20 split, full BoM context, production prompt",
    }

    if args.mode == "stats":
        report["dataset_stats"] = eval_dataset_stats(projects)

    else:
        train, test = split_train_test(projects, test_ratio=0.20, seed=args.seed)
        print(f"\nSplit → train: {len(train)}  |  test: {len(test)}")
        report["split"] = {"train_size": len(train), "test_size": len(test),
                           "test_ids": [p["id"] for p in test]}

        eval_dataset_stats(projects)
        print()
        build_holdout_index(train)

        # Build train lookup for full BoM enrichment
        train_by_id = {str(p["id"]): p for p in train}

        try:
            if args.mode in ("full", "retrieval-only"):
                report["retrieval"] = eval_retrieval(test, train, verbose=args.verbose)

            if args.mode == "full" and not args.no_llm:
                report["llm_accuracy"] = eval_llm_accuracy(
                    test, train_by_id, all_blocks, all_armoires,
                    n=args.n, verbose=args.verbose, workers=args.workers,
                )
            elif args.no_llm:
                print("\n  [--no-llm] Skipping LLM evaluation.")

        finally:
            print()
            teardown_holdout_index()

    # Save report
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*62}")
    print(f"Report → {report_path}")
    print("=" * 62)


if __name__ == "__main__":
    main()
