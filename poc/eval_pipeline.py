#!/usr/bin/env python3
"""
eval_pipeline.py – CETIE AI Configurator accuracy evaluation (held-out split)
==============================================================================

Proper evaluation using a held-out test set to prevent data leakage.

Methodology
-----------
  1. Split 119 projects into 80% train / 20% test (stratified by product_type).
  2. Build a TEMPORARY ChromaDB collection from train projects only.
  3. For retrieval test  : query with test project's client_request → the system
     has never seen it → measures true semantic generalisation.
  4. For LLM test        : query with test project's client_request, the similar
     context returned will NOT contain the test project itself → true prediction.
  5. Compare LLM output against test project ground truth.
  6. Tear down the temporary collection when done.

Retrieval metrics (held-out)
----------------------------
  Since the test project is NOT in the index we cannot measure "did it find itself".
  Instead we measure:
    - product_type_match@k  : top-k results include a project with the same product_type
    - sector_match@k        : top-k results include a project with the same sector
    - avg_top1_similarity   : mean cosine similarity of best match (proxy for relevance)

LLM metrics
-----------
    - Category Recall    : % of GT categories the LLM correctly populates
    - Price MAPE         : mean absolute % error vs ground-truth base_price
    - Hours Fab MAPE     : same for fabrication hours
    - Hours Prog MAPE    : same for programmation hours
    (micro-projects < €500 excluded from price/hours MAPE — unreliable denominator)

Usage
-----
  # Held-out eval (recommended — no data leakage):
  python3 poc/eval_pipeline.py --mode holdout --n 20

  # Held-out + verbose per-project breakdown:
  python3 poc/eval_pipeline.py --mode holdout --n 20 --verbose

  # Dataset stats only:
  python3 poc/eval_pipeline.py --mode stats

  # Legacy self-query mode (shows inflated numbers — for reference only):
  python3 poc/eval_pipeline.py --mode legacy --n 10
"""

import os
import sys
import json
import random
import argparse
import time
import datetime
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

import chromadb
import rag

# ── Constants ─────────────────────────────────────────────────────────────────
DATA_PATH    = BASE_DIR / "data" / "yearly_projects_2026.json"
REPORT_PATH  = BASE_DIR / "data" / "eval_report_holdout_2026.json"
YEAR         = "2026"
HOLDOUT_COLL = "yearly_projects_holdout_train_2026"   # temporary collection name

CHASSIS_SUBS = {
    "04_internal_chassis_power",
    "04_internal_chassis_control",
    "04_internal_chassis_automation",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_projects():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def project_ground_truth(p: dict) -> dict:
    conf = p.get("configuration", {})
    cats = conf.get("by_category", {})
    raw  = set(c for c, items in cats.items() if items)
    # Expand 04_internal_chassis → sub-categories
    normalised = set()
    for c in raw:
        if c == "04_internal_chassis":
            normalised.update(CHASSIS_SUBS)
        else:
            normalised.add(c)
    scoreable = normalised - {"04_internal_chassis"}
    return {
        "id":                  p["id"],
        "client":              p.get("client") or "",
        "description":         p.get("description") or p.get("divalto_designation") or "",
        "product_type":        p.get("product_type") or "",
        "sector":              p.get("sector") or p.get("metier") or "EAU",
        "nb_motors":           p.get("nb_motors"),
        "base_price":          conf.get("base_price", 0),
        "hours_fabrication":   conf.get("hours_fabrication", 0),
        "hours_programmation": conf.get("hours_programmation", 0),
        "nb_components":       conf.get("nb_components", 0),
        "categories_present":  sorted(scoreable),
        "key_components":      conf.get("key_components", []),
        "client_request":      p.get("client_request", ""),
    }


def _pct_error(predicted, actual) -> Optional[float]:
    if not actual:
        return None
    return abs(predicted - actual) / abs(actual) * 100


def bar(v, width=20, char="█") -> str:
    v = max(0.0, min(1.0, v))
    filled = round(v * width)
    return char * filled + "░" * (width - filled)


# ══════════════════════════════════════════════════════════════════════════════
# Held-out index management
# ══════════════════════════════════════════════════════════════════════════════

def _project_to_text(p: dict) -> str:
    """Mirror rag._project_to_text — improved architecture-aware embedding."""
    return rag._project_to_text(p)


def build_holdout_index(train_projects: list) -> None:
    """Embed train_projects into a temporary ChromaDB collection."""
    print(f"  Building temporary train index ({len(train_projects)} projects) …")
    oai    = rag._openai_client()
    chroma = rag._chroma_client()

    try:
        chroma.delete_collection(HOLDOUT_COLL)
    except Exception:
        pass

    collection = chroma.create_collection(
        name=HOLDOUT_COLL,
        metadata={"hnsw:space": "cosine"},
    )

    ids, embeddings, documents, metadatas = [], [], [], []
    for idx, p in enumerate(train_projects):
        text = _project_to_text(p)
        if not text.strip():
            continue
        vec = rag.embed_text(text, oai)
        conf = p.get("configuration", {})
        ids.append(f"{p['id']}_{idx}")
        embeddings.append(vec)
        documents.append(text)
        def _ms(v): return str(v) if v is not None else ""
        metadatas.append({
            "id":              _ms(p.get("id")),
            "product_type":    _ms(p.get("product_type")),
            "sector":          _ms(p.get("sector") or p.get("metier") or "EAU"),
            "client":          _ms(p.get("client")),
            "base_price":      _ms(conf.get("base_price", 0)),
            "hours_fab":       _ms(conf.get("hours_fabrication", 0)),
            "hours_prog":      _ms(conf.get("hours_programmation", 0)),
            "divalto_desig":   _ms(p.get("divalto_designation"))[:100],
            "tags":            " ".join(p.get("tags") or [])[:200],
            "nb_motors":       _ms(p.get("nb_motors")),
        })

    collection.add(ids=ids, embeddings=embeddings,
                   documents=documents, metadatas=metadatas)
    print(f"  Train index ready — {len(ids)} projects embedded.")


def query_holdout_index(query_text: str, n_results: int = 5) -> list:
    """Query the temporary train index."""
    chroma     = rag._chroma_client()
    collection = chroma.get_collection(HOLDOUT_COLL)
    oai        = rag._openai_client()
    query_vec  = rag.embed_text(query_text, oai)

    results = collection.query(
        query_embeddings=[query_vec],
        n_results=min(n_results, collection.count()),
        include=["metadatas", "distances"],
    )

    similar = []
    for i, uid in enumerate(results["ids"][0]):
        meta  = results["metadatas"][0][i]
        score = round(1.0 - results["distances"][0][i], 3)
        similar.append({
            "id":              meta.get("id", uid),
            "product_type":    meta.get("product_type", ""),
            "sector":          meta.get("sector", ""),
            "client":          meta.get("client", ""),
            "base_price":      float(meta.get("base_price", 0) or 0),
            "hours_fab":       float(meta.get("hours_fab", 0) or 0),
            "hours_prog":      float(meta.get("hours_prog", 0) or 0),
            "divalto_desig":   meta.get("divalto_desig", ""),
            "tags":            meta.get("tags", ""),
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
    """
    Stratified split by product_type so each type is represented in both sets.
    Returns (train, test).
    """
    random.seed(seed)

    # Group by product_type
    groups = {}
    for p in projects:
        pt = p.get("product_type", "unknown")
        groups.setdefault(pt, []).append(p)

    train, test = [], []
    for pt, members in groups.items():
        random.shuffle(members)
        n_test = max(1, round(len(members) * test_ratio)) if len(members) >= 3 else 0
        test.extend(members[:n_test])
        train.extend(members[n_test:])

    # Any remainder with only 1-2 members goes entirely to train
    random.shuffle(test)
    return train, test


# ══════════════════════════════════════════════════════════════════════════════
# LLM call (mirrors app.py streaming endpoint logic)
# ══════════════════════════════════════════════════════════════════════════════

def _call_config_llm(client_request: str,
                     similar_quotes: list,
                     similar_projects: list) -> dict:
    try:
        import anthropic as ant
    except ImportError:
        raise RuntimeError("anthropic package not installed")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = ant.Anthropic(api_key=api_key)

    quotes_text = ""
    for q in similar_quotes[:3]:
        quotes_text += (
            f"\n- [{q.get('product_type','')}] {q.get('summary','')} "
            f"(score: {q.get('similarity_score',0):.2f})"
        )

    projects_text = ""
    for proj in similar_projects[:5]:
        conf  = proj.get("configuration", {})
        cats  = conf.get("by_category", {})
        comps = []
        for cat, items in cats.items():
            for item in items:
                comps.append(
                    f"  • [{cat}] {item.get('designation','')} "
                    f"x{item.get('quantity',1)} @ {item.get('unit_price',0)}€"
                )
        projects_text += (
            f"\n\nDEVIS {proj.get('id','')} "
            f"({proj.get('client','')} – {proj.get('description','')}) "
            f"score={proj.get('similarity_score',0):.2f}\n"
            f"  Prix: {conf.get('base_price',0)}€ | "
            f"Fab: {conf.get('hours_fabrication',0)}h | "
            f"Prog: {conf.get('hours_programmation',0)}h\n"
            + "\n".join(comps[:15])
        )

    # Category hint from similar projects
    seen_cats = set()
    for proj in similar_projects[:3]:
        for cat, items in proj.get("configuration", {}).get("by_category", {}).items():
            if items:
                seen_cats.add(cat)
    seen_cats.discard("04_internal_chassis")
    if any(c.startswith("04_internal") for c in seen_cats):
        seen_cats.add("04_internal_chassis_power")
    cat_hint = (
        f"\nIMPORTANT — Similar DEVIS used these categories: "
        f"{', '.join(sorted(seen_cats))}. Populate ALL of them with real items.\n"
    ) if seen_cats else ""

    prompt = f"""Tu es un expert en configuration d'armoires électriques industrielles CETIE.

DEMANDE CLIENT :
{client_request}

DEVIS SIMILAIRES DE RÉFÉRENCE :
{projects_text if projects_text else "Aucun devis similaire disponible."}

CITATIONS HISTORIQUES :
{quotes_text if quotes_text else "Aucune citation similaire."}
{cat_hint}
RÈGLES OBLIGATOIRES pour les catégories BoM :
- 01_cabinet_enclosure : TOUJOURS remplir — chaque armoire a une enveloppe.
- 04_internal_chassis_power : TOUJOURS remplir pour les projets pompes/moteurs.
- 06_door_controls : TOUJOURS remplir — boutons, voyants, sélecteurs en façade.
- 11_labor : TOUJOURS remplir — heures câblage + heures programmation séparées.
- 02_equipment_on_side : si disjoncteurs latéraux ou prises de service.
- 04_internal_chassis_control : si relais, temporisateurs ou circuits de contrôle.
- 04_internal_chassis_automation : si automate, variateur ou module communication.
- Laisser [] UNIQUEMENT si la catégorie ne s'applique vraiment pas.

Génère une configuration JSON complète. Réponds UNIQUEMENT avec du JSON valide.

{{
  "product_type": "...",
  "estimated_price": <number>,
  "hours_fabrication": <number>,
  "hours_programmation": <number>,
  "nb_motors": <number or null>,
  "bom_categories": {{
    "01_cabinet_enclosure":           [{{"designation": "...", "quantity": 1, "unit_price": 0}}],
    "02_equipment_on_side":           [],
    "04_internal_chassis_power":      [],
    "04_internal_chassis_control":    [],
    "04_internal_chassis_automation": [],
    "05_equipment_on_top":            [],
    "06_door_controls":               [],
    "07_supplied_separately":         [],
    "09_commissioning":               [],
    "10_packaging":                   [],
    "11_labor":                       [{{"designation": "Main d'oeuvre cablage", "quantity": 1, "hours": 0, "hourly_rate": 65}}, {{"designation": "Main d'oeuvre programmation", "quantity": 1, "hours": 0, "hourly_rate": 75}}],
    "12_options":                     []
  }},
  "rationale": "..."
}}"""

    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[:-3].strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            import json_repair
            return json_repair.loads(raw)
        except Exception:
            return {"_parse_error": raw[:300]}


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 – Held-out retrieval quality
# ══════════════════════════════════════════════════════════════════════════════

def eval_holdout_retrieval(test_projects: list,
                           train_projects: list,
                           k_values=(1, 3, 5),
                           verbose=False) -> dict:
    """
    Query the TRAIN-only index with each TEST project's client_request.
    The test project is guaranteed NOT to be in the index.

    Measures:
      - product_type_match@k  : retrieved top-k contains same product_type
      - sector_match@k        : retrieved top-k contains same sector/metier
      - avg_top1_similarity   : mean cosine similarity of best match
    """
    print(f"\n{'─'*60}")
    print("TEST 1 – Held-out Retrieval Quality")
    print(f"  Train size: {len(train_projects)}  |  Test size: {len(test_projects)}")
    print(f"{'─'*60}")

    testable = [p for p in test_projects if len(p.get("client_request", "")) > 40]

    pt_hits    = {k: 0 for k in k_values}
    sec_hits   = {k: 0 for k in k_values}
    top1_scores = []
    details    = []
    total      = 0

    for p in testable:
        gt  = project_ground_truth(p)
        pid = gt["id"]

        results = query_holdout_index(gt["client_request"][:500], n_results=max(k_values))
        if not results:
            continue

        top1_scores.append(results[0]["similarity_score"])
        retrieved_types   = [r["product_type"] for r in results]
        retrieved_sectors = [r["sector"]        for r in results]

        for k in k_values:
            if gt["product_type"] in retrieved_types[:k]:
                pt_hits[k] += 1
            if gt["sector"] in retrieved_sectors[:k]:
                sec_hits[k] += 1

        total += 1
        detail = {
            "id":             pid,
            "product_type":   gt["product_type"],
            "sector":         gt["sector"],
            "top1_id":        results[0]["id"],
            "top1_type":      results[0]["product_type"],
            "top1_score":     results[0]["similarity_score"],
            "type_match_top1": gt["product_type"] == results[0]["product_type"],
            "top5":           [(r["id"], r["product_type"], r["similarity_score"]) for r in results[:5]],
        }
        details.append(detail)

        if verbose:
            match = "✓" if detail["type_match_top1"] else "✗"
            print(f"  {pid:<22} [{gt['product_type'][:30]:<30}]"
                  f" → {match} {results[0]['product_type'][:30]:<30} score={results[0]['similarity_score']:.3f}")

    pt_match  = {k: pt_hits[k]  / total if total else 0 for k in k_values}
    sec_match = {k: sec_hits[k] / total if total else 0 for k in k_values}
    avg_top1  = sum(top1_scores) / len(top1_scores) if top1_scores else 0

    print(f"\n  Test projects queried : {total}")
    print(f"  Avg top-1 similarity  : {avg_top1:.3f}  (1.0 = perfect match)")
    print()
    for k in k_values:
        print(f"  Product-type match@{k} : {pt_match[k]:.0%}  {bar(pt_match[k])}")
    print()
    for k in k_values:
        print(f"  Sector match@{k}       : {sec_match[k]:.0%}  {bar(sec_match[k])}")

    return {
        "total":           total,
        "avg_top1_sim":    round(avg_top1, 3),
        "product_type_match": {str(k): round(v, 3) for k, v in pt_match.items()},
        "sector_match":       {str(k): round(v, 3) for k, v in sec_match.items()},
        "details":         details,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 – Held-out LLM accuracy
# ══════════════════════════════════════════════════════════════════════════════

def eval_holdout_llm(test_projects: list, n: int = 15, verbose=False) -> dict:
    """
    For N held-out test projects:
      - Retrieve similar quotes from the FULL historical index (curated)
      - Retrieve similar projects from the TRAIN-ONLY holdout index
        (test project is NOT in the index — no data leakage)
      - Call LLM, compare output vs ground truth
    """
    print(f"\n{'─'*60}")
    print(f"TEST 2 – Held-out LLM Accuracy (n={n})")
    print(f"  Test project is NEVER in the retrieved context.")
    print(f"{'─'*60}")

    candidates = [
        p for p in test_projects
        if len(p.get("client_request", "")) > 80
        and (
            p.get("configuration", {}).get("base_price", 0) > 100
            or p.get("configuration", {}).get("hours_fabrication", 0) > 0
        )
    ]
    random.shuffle(candidates)
    subset = candidates[:n]

    if not subset:
        print("  [WARN] No testable projects in test set.")
        return {}

    results              = []
    category_recall_sum  = 0.0
    category_prec_sum    = 0.0
    price_errors         = []
    hours_fab_errors     = []
    hours_prog_errors    = []

    for idx, p in enumerate(subset):
        gt  = project_ground_truth(p)
        pid = gt["id"]
        print(f"\n  [{idx+1}/{len(subset)}] {pid} – {gt['description'][:55]}")

        query   = gt["client_request"][:500]
        sim_q   = rag.retrieve_similar(query, n_results=3)           # curated quotes only
        sim_p   = query_holdout_index(query, n_results=5)            # train projects only

        # Build project dicts for the LLM prompt — include hours and designation
        sim_p_for_llm = [
            {
                "id":           r["id"],
                "client":       r["client"],
                "description":  r.get("divalto_desig") or r["product_type"],
                "product_type": r["product_type"],
                "similarity_score": r["similarity_score"],
                "tags":         r.get("tags", "").split(),
                "configuration": {
                    "base_price":          r["base_price"],
                    "hours_fabrication":   r["hours_fab"],
                    "hours_programmation": r["hours_prog"],
                    "by_category":         {},
                },
            }
            for r in sim_p
        ]

        t0 = time.time()
        try:
            cfg = _call_config_llm(gt["client_request"], sim_q, sim_p_for_llm)
        except Exception as e:
            print(f"    LLM ERROR: {e}")
            results.append({"id": pid, "error": str(e)})
            continue
        elapsed = time.time() - t0

        if "_parse_error" in cfg:
            print(f"    JSON PARSE ERROR")
            results.append({"id": pid, "error": "json_parse", "raw": cfg["_parse_error"]})
            continue

        # ── Category metrics ─────────────────────────────────────────────────
        scoreable_gt = set(gt["categories_present"])
        llm_cats     = set(
            k for k, v in cfg.get("bom_categories", {}).items()
            if isinstance(v, list) and len(v) > 0
        )
        tp                 = scoreable_gt & llm_cats
        category_recall    = len(tp) / len(scoreable_gt) if scoreable_gt else 1.0
        category_precision = len(tp) / len(llm_cats)     if llm_cats    else 0.0
        category_recall_sum += category_recall
        category_prec_sum   += category_precision

        # ── Hours metrics ────────────────────────────────────────────────────
        llm_fab  = cfg.get("hours_fabrication", 0) or 0
        llm_prog = cfg.get("hours_programmation", 0) or 0
        gt_fab   = gt["hours_fabrication"]
        gt_prog  = gt["hours_programmation"]

        # ── Price metrics ────────────────────────────────────────────────────
        llm_price = cfg.get("estimated_price", 0) or 0
        gt_price  = gt["base_price"]
        price_err = _pct_error(llm_price, gt_price)
        if price_err is not None and gt_price >= 500:
            price_errors.append(price_err)
        # micro_project: no price AND no hours → truly trivial project
        row_micro_flag = (gt_price == 0 and gt_fab == 0)
        fab_err  = _pct_error(llm_fab, gt_fab)
        prog_err = _pct_error(llm_prog, gt_prog)
        scoreable = gt_price >= 500 or gt_fab > 0
        if fab_err  is not None and scoreable: hours_fab_errors.append(fab_err)
        if prog_err is not None and gt_prog > 0: hours_prog_errors.append(prog_err)

        row = {
            "id":                  pid,
            "description":         gt["description"],
            "gt_price":            gt_price,
            "llm_price":           llm_price,
            "price_err_pct":       round(price_err, 1) if price_err is not None else None,
            "gt_hours_fab":        gt_fab,
            "llm_hours_fab":       llm_fab,
            "fab_err_pct":         round(fab_err, 1)  if fab_err  is not None else None,
            "gt_hours_prog":       gt_prog,
            "llm_hours_prog":      llm_prog,
            "prog_err_pct":        round(prog_err, 1) if prog_err is not None else None,
            "gt_categories":       sorted(scoreable_gt),
            "llm_categories":      sorted(llm_cats),
            "missed_categories":   sorted(scoreable_gt - llm_cats),
            "extra_categories":    sorted(llm_cats - scoreable_gt),
            "category_recall":     round(category_recall, 3),
            "category_precision":  round(category_precision, 3),
            "micro_project":       row_micro_flag,
            "top1_train_id":       sim_p[0]["id"] if sim_p else None,
            "top1_train_score":    sim_p[0]["similarity_score"] if sim_p else 0,
            "llm_elapsed_s":       round(elapsed, 1),
        }
        results.append(row)

        if verbose:
            print(f"    GT  price: {gt_price:>8.0f}€  |  LLM: {llm_price:>8.0f}€"
                  + (f"  err={price_err:.0f}%" if price_err is not None else ""))
            print(f"    GT  fab:   {gt_fab:>6.1f}h   |  LLM: {llm_fab:>6.1f}h"
                  + (f"  err={fab_err:.0f}%" if fab_err is not None else ""))
            print(f"    GT  prog:  {gt_prog:>6.1f}h   |  LLM: {llm_prog:>6.1f}h")
            print(f"    Cat recall: {category_recall:.0%}  missed={sorted(scoreable_gt-llm_cats)}")
            print(f"    Top-1 train ref: {sim_p[0]['id'] if sim_p else 'none'} "
                  f"(score={sim_p[0]['similarity_score']:.3f} | {sim_p[0]['product_type'][:40]})" if sim_p else "")
        else:
            p_str  = f"{price_err:.0f}%" if price_err is not None else "N/A"
            fb_str = f"{fab_err:.0f}%"   if fab_err  is not None else "N/A"
            print(f"    price_err={p_str:>6}  fab_err={fb_str:>6}  "
                  f"cat_recall={category_recall:.0%}  ({elapsed:.1f}s)")

    n_ok = len([r for r in results if "error" not in r])

    summary = {
        "n_tested":                len(subset),
        "n_ok":                    n_ok,
        "mean_category_recall":    round(category_recall_sum / n_ok, 3) if n_ok else 0,
        "mean_category_precision": round(category_prec_sum   / n_ok, 3) if n_ok else 0,
        "mean_price_mape":         round(sum(price_errors) / len(price_errors), 1) if price_errors else None,
        "median_price_mape":       round(sorted(price_errors)[len(price_errors)//2], 1) if price_errors else None,
        "mean_fab_mape":           round(sum(hours_fab_errors)  / len(hours_fab_errors),  1) if hours_fab_errors  else None,
        "mean_prog_mape":          round(sum(hours_prog_errors) / len(hours_prog_errors), 1) if hours_prog_errors else None,
        "n_price_evaluated":       len(price_errors),
        "n_micro_excluded":        sum(1 for r in results if r.get("micro_project")),
        "results":                 results,
    }

    print(f"\n  ┌{'─'*52}┐")
    print(f"  │  HOLDOUT SUMMARY  ({n_ok}/{len(subset)} successful)            │")
    print(f"  │  (test projects were NEVER in the train index)   │")
    print(f"  ├{'─'*52}┤")
    cr  = summary["mean_category_recall"]
    cp  = summary["mean_category_precision"]
    pm  = summary["mean_price_mape"]
    mdm = summary["median_price_mape"]
    fm  = summary["mean_fab_mape"]
    pgm = summary["mean_prog_mape"]
    print(f"  │  Category Recall    : {cr:.0%}  {bar(cr)}")
    print(f"  │  Category Precision : {cp:.0%}  {bar(cp)}")
    if pm:
        print(f"  │  Price MAPE (mean)  : {pm:.1f}%  ({summary['n_price_evaluated']} projects ≥€500)")
        print(f"  │  Price MAPE (median): {mdm:.1f}%")
    else:
        print(f"  │  Price MAPE         : N/A")
    print(f"  │  Hours Fab MAPE     : {fm:.1f}%"  if fm  else "  │  Hours Fab MAPE     : N/A")
    print(f"  │  Hours Prog MAPE    : {pgm:.1f}%" if pgm else "  │  Hours Prog MAPE    : N/A")
    print(f"  └{'─'*52}┘")

    return summary


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 – Dataset stats
# ══════════════════════════════════════════════════════════════════════════════

def eval_dataset_stats(projects: list) -> dict:
    print(f"\n{'─'*60}")
    print("Dataset Stats")
    print(f"{'─'*60}")
    total      = len(projects)
    w_request  = sum(1 for p in projects if len(p.get("client_request", "")) > 40)
    w_emails   = sum(1 for p in projects if p.get("emails"))
    w_comps    = sum(1 for p in projects if p.get("configuration", {}).get("nb_components", 0) > 0)
    w_price    = sum(1 for p in projects if p.get("configuration", {}).get("base_price", 0) > 0)
    w_hours    = sum(1 for p in projects if p.get("configuration", {}).get("hours_fabrication", 0) > 0)
    avg_price  = sum(p.get("configuration", {}).get("base_price", 0) for p in projects) / total
    avg_fab    = sum(p.get("configuration", {}).get("hours_fabrication", 0) for p in projects) / total

    cat_counts = {}
    for p in projects:
        for cat in p.get("configuration", {}).get("by_category", {}):
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print(f"  Total    : {total}  |  With request: {w_request} ({w_request/total:.0%})"
          f"  |  With price: {w_price} ({w_price/total:.0%})"
          f"  |  With hours: {w_hours} ({w_hours/total:.0%})")
    print(f"  Avg price: €{avg_price:.0f}  |  Avg fab: {avg_fab:.1f}h  |  Clients: {len(set(p.get('client','') for p in projects))}")
    print(f"  Category distribution:")
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f"    {cat:<42} {cnt:>3} ({cnt/total:.0%})  {bar(cnt/total, 12)}")

    return {"total": total, "with_request": w_request, "avg_price": round(avg_price),
            "category_distribution": cat_counts}


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="CETIE pipeline evaluation (held-out split)")
    parser.add_argument("--mode",    choices=["holdout", "stats", "legacy"],
                        default="holdout",
                        help="holdout = proper eval | stats = data only | legacy = old leaky eval")
    parser.add_argument("--n",       type=int, default=15,
                        help="Number of test projects to evaluate with LLM (default: 15)")
    parser.add_argument("--seed",    type=int, default=42)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--report",  default=str(REPORT_PATH))
    parser.add_argument("--no-llm",  action="store_true",
                        help="Skip LLM calls, only run retrieval test")
    args = parser.parse_args()

    random.seed(args.seed)

    print("=" * 60)
    print("CETIE AI Configurator – Held-out Evaluation")
    print(f"Date : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode : {args.mode}  |  seed={args.seed}  |  n={args.n}")
    print("=" * 60)

    if not DATA_PATH.exists():
        print(f"[ERROR] {DATA_PATH} not found — run parse_yearly_data.py first")
        sys.exit(1)

    projects = load_projects()
    print(f"\nLoaded {len(projects)} projects")

    report = {
        "generated_at": datetime.datetime.now().isoformat(),
        "mode": args.mode,
        "seed": args.seed,
        "methodology": "held-out 80/20 split — test projects excluded from RAG index",
    }

    if args.mode == "stats":
        report["dataset_stats"] = eval_dataset_stats(projects)

    elif args.mode == "holdout":
        train, test = split_train_test(projects, test_ratio=0.20, seed=args.seed)
        print(f"\nSplit → train: {len(train)}  |  test: {len(test)}")

        report["split"] = {
            "train_size": len(train),
            "test_size":  len(test),
            "test_ids":   [p["id"] for p in test],
        }

        eval_dataset_stats(projects)

        # Build temporary index on train only
        print()
        build_holdout_index(train)

        try:
            # Retrieval test
            report["retrieval"] = eval_holdout_retrieval(
                test, train, k_values=(1, 3, 5), verbose=args.verbose
            )

            # LLM accuracy test
            if not args.no_llm:
                report["llm_accuracy"] = eval_holdout_llm(
                    test, n=args.n, verbose=args.verbose
                )
            else:
                print("\n  [--no-llm] Skipping LLM evaluation.")

        finally:
            print()
            teardown_holdout_index()

    elif args.mode == "legacy":
        print("\n⚠️  LEGACY MODE — uses self-query (data leakage). Numbers are inflated.")
        print("    Use --mode holdout for honest evaluation.\n")
        # Import original functions if needed — not implemented here
        print("  Legacy mode not available in this version. Use --mode holdout.")

    # Save report
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"Report → {report_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
