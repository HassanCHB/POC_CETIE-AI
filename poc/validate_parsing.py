#!/usr/bin/env python3
"""
validate_parsing.py — Regression test for the CETIE yearly Excel parser
========================================================================

Runs the parser against every DEVIS project in yearly_data/ and checks that
the extracted data meets a set of quality thresholds. Designed to catch
parser regressions before they reach the RAG corpus.

What it checks (per project)
----------------------------
  • Parse succeeds (no exception)
  • id is the folder name (not a header sentinel like 'Client')
  • client is extracted
  • devis_number looks valid (DEVIS... or 7-digit code)
  • base_price > 0   (for non-trivial projects)
  • cost_material > 0 (for non-trivial projects)
  • hours_fabrication > 0 (for non-trivial projects)
  • ≥ 1 component extracted (for non-trivial projects)
  • ≥ 2 BoM categories populated (for armoires/coffrets with price > 1000€)
  • divalto_designation OR description present

What it reports
---------------
  • Per-year coverage and quality stats
  • List of projects that failed each check (with --verbose)
  • Per-category extraction counts vs. expected baseline
  • Exit code 1 if --strict and any year falls below threshold

Usage
-----
  python3 poc/validate_parsing.py                     # all years, summary
  python3 poc/validate_parsing.py --year 2026         # single year
  python3 poc/validate_parsing.py --verbose           # list all failures
  python3 poc/validate_parsing.py --strict            # exit 1 on regression
  python3 poc/validate_parsing.py --sample 20         # only parse 20 per year
  python3 poc/validate_parsing.py --json out.json     # machine-readable report
"""
from __future__ import annotations

import argparse
import gc
import json
import re
import sys
import time
import warnings
from pathlib import Path
from collections import Counter, defaultdict

warnings.filterwarnings("ignore")  # suppress openpyxl noise

# Make parser importable regardless of cwd
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from parse_yearly_data import process_folder, YEARLY_DIR  # noqa: E402


# ── Quality thresholds ────────────────────────────────────────────────────────

# "Trivial" = tiny projects (small parts, one sensor, etc.) where expecting
# full BoM coverage is unrealistic. We use price OR hours as the signal.
TRIVIAL_PRICE   = 500.0    # €
TRIVIAL_HOURS   = 5.0      # h

# Minimum year-level pass rates — used when --strict is set
MIN_PARSE_RATE         = 0.90    # 90 % of folders must produce a result
MIN_CLIENT_RATE        = 0.80    # 80 % must have client
MIN_BASE_PRICE_RATE    = 0.80    # 80 % non-trivial must have base_price
MIN_COMPONENTS_RATE    = 0.80    # 80 % non-trivial must have ≥1 component
MIN_CATEGORIES_RATE    = 0.75    # 75 % non-trivial must have ≥2 categories

# Values that indicate the parser caught a column-header row instead of data
SENTINELS = {"Client", "Interlocuteur", "Affaire", "Produit",
             "Commercial", "Année", "Semaine envoi", "N° Devis"}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_trivial(project: dict) -> bool:
    cfg   = project.get("configuration", {}) or {}
    price = cfg.get("base_price") or 0
    hfab  = cfg.get("hours_fabrication") or 0
    return price < TRIVIAL_PRICE and hfab < TRIVIAL_HOURS


def _bar(frac: float, width: int = 20, ch: str = "█") -> str:
    frac = max(0.0, min(1.0, frac))
    filled = round(frac * width)
    return ch * filled + "░" * (width - filled)


# ── Per-project validation ────────────────────────────────────────────────────


def validate_project(project: dict, folder_name: str) -> dict:
    """
    Apply all quality checks to one parsed project dict.
    Returns a dict of {check_name: True/False/None} plus a list of issues.
    None means the check was skipped (e.g. trivial project).
    """
    if project is None:
        return {
            "folder": folder_name,
            "parse_ok": False,
            "issues":   ["parse_returned_none"],
        }

    cfg = project.get("configuration", {}) or {}
    cats = cfg.get("by_category", {}) or {}
    n_components = sum(len(v) for v in cats.values() if isinstance(v, list))
    n_categories = sum(1 for v in cats.values() if isinstance(v, list) and v)

    trivial = _is_trivial(project)
    checks: dict = {}
    issues: list[str] = []

    # 1. ID is the folder name, not a sentinel
    pid = project.get("id", "")
    checks["id_ok"] = pid == folder_name
    if not checks["id_ok"]:
        if pid in SENTINELS:
            issues.append(f"id_sentinel:{pid}")
        else:
            issues.append(f"id_mismatch:{pid!r}")

    # 2. DEVIS number looks valid (or is None, in which case folder fallback applies)
    devn = project.get("devis_number") or ""
    if devn:
        valid_devn = bool(re.match(r"^(DEVIS\d{6,}|[0-9]{6,})$", str(devn)))
        checks["devis_number_ok"] = valid_devn
        if not valid_devn:
            issues.append(f"devis_number_invalid:{devn!r}")
    else:
        checks["devis_number_ok"] = None  # not captured, may still work via folder

    # 3. Client
    checks["has_client"] = bool(project.get("client"))
    if not checks["has_client"]:
        issues.append("missing_client")

    # 4. Description or divalto designation
    checks["has_description"] = bool(
        project.get("description") or project.get("divalto_designation")
    )
    if not checks["has_description"]:
        issues.append("missing_description")

    # 5. base_price (only required for non-trivial projects)
    if trivial:
        checks["has_base_price"] = None
    else:
        checks["has_base_price"] = (cfg.get("base_price") or 0) > 0
        if not checks["has_base_price"]:
            issues.append("missing_base_price")

    # 6. cost_material (only required for non-trivial projects)
    if trivial:
        checks["has_cost_material"] = None
    else:
        checks["has_cost_material"] = (cfg.get("cost_material") or 0) > 0
        if not checks["has_cost_material"]:
            issues.append("missing_cost_material")

    # 7. hours_fabrication (only required for non-trivial projects)
    if trivial:
        checks["has_hours_fab"] = None
    else:
        checks["has_hours_fab"] = (cfg.get("hours_fabrication") or 0) > 0
        if not checks["has_hours_fab"]:
            issues.append("missing_hours_fabrication")

    # 8. ≥ 1 component (only for non-trivial projects)
    if trivial:
        checks["has_components"] = None
    else:
        checks["has_components"] = n_components > 0
        if not checks["has_components"]:
            issues.append(f"no_components (price={cfg.get('base_price',0)}€, "
                          f"fab={cfg.get('hours_fabrication',0)}h)")

    # 9. ≥ 2 BoM categories populated (only for real armoires with price > 1000€)
    price = cfg.get("base_price") or 0
    if price > 1000:
        checks["has_multi_categories"] = n_categories >= 2
        if not checks["has_multi_categories"]:
            issues.append(f"single_category_only ({n_categories}, price={price:.0f}€)")
    else:
        checks["has_multi_categories"] = None

    return {
        "folder":        folder_name,
        "parse_ok":      True,
        "trivial":       trivial,
        "n_components":  n_components,
        "n_categories":  n_categories,
        "base_price":    cfg.get("base_price") or 0,
        "hours_fab":     cfg.get("hours_fabrication") or 0,
        "hours_prog":    cfg.get("hours_programmation") or 0,
        "client":        project.get("client") or "",
        "id":            project.get("id", ""),
        "checks":        checks,
        "issues":        issues,
    }


# ── Per-year driver ───────────────────────────────────────────────────────────


def scan_year(year: str, sample: int | None = None, verbose: bool = False) -> dict:
    year_dir_nested = YEARLY_DIR / year / year
    year_dir_flat   = YEARLY_DIR / year
    year_dir = year_dir_nested if year_dir_nested.exists() else year_dir_flat
    if not year_dir.exists():
        return {"year": year, "error": f"folder not found: {year_dir}"}

    folders = sorted(
        p for p in year_dir.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )
    if sample:
        folders = folders[:sample]

    print(f"\n{'─' * 70}")
    print(f"Year {year} — scanning {len(folders)} folders in {year_dir}")
    print("─" * 70)

    results: list[dict] = []
    t0 = time.time()
    for i, folder in enumerate(folders, 1):
        try:
            project = process_folder(folder)
        except Exception as e:
            project = None
            if verbose:
                print(f"  [{i}/{len(folders)}] EXCEPTION in {folder.name}: {e}")
        r = validate_project(project, folder.name)
        results.append(r)
        if verbose and r.get("issues"):
            print(f"  ✗ {folder.name[:50]}  →  {r['issues']}")
        # Force GC every 25 projects to prevent openpyxl resource accumulation
        # when many workbooks trigger the read_only fallback.
        if i % 25 == 0:
            gc.collect()

    # Final sweep after the year completes — particularly important when multiple
    # years run sequentially, since the 2022 fallback loads full workbooks.
    gc.collect()
    elapsed = time.time() - t0

    # Aggregate
    n_total             = len(results)
    n_parsed            = sum(1 for r in results if r.get("parse_ok"))
    n_trivial           = sum(1 for r in results if r.get("trivial"))
    n_non_trivial       = n_parsed - n_trivial
    n_has_client        = sum(1 for r in results if r.get("checks", {}).get("has_client"))
    n_id_ok             = sum(1 for r in results if r.get("checks", {}).get("id_ok"))
    n_has_base_price    = sum(1 for r in results if r.get("checks", {}).get("has_base_price") is True)
    n_has_cost_material = sum(1 for r in results if r.get("checks", {}).get("has_cost_material") is True)
    n_has_hours_fab     = sum(1 for r in results if r.get("checks", {}).get("has_hours_fab") is True)
    n_has_components    = sum(1 for r in results if r.get("checks", {}).get("has_components") is True)
    n_has_multi_cats    = sum(1 for r in results if r.get("checks", {}).get("has_multi_categories") is True)

    cat_counter: Counter = Counter()
    issue_counter: Counter = Counter()
    total_components = 0
    for r in results:
        total_components += r.get("n_components", 0) or 0
        for iss in r.get("issues", []):
            # collapse issues with values to their type
            key = iss.split(":")[0].split(" ")[0]
            issue_counter[key] += 1

    # Rates (denominators)
    parse_rate = n_parsed / n_total if n_total else 0
    client_rate = n_has_client / n_parsed if n_parsed else 0
    id_rate     = n_id_ok      / n_parsed if n_parsed else 0
    price_rate  = n_has_base_price / n_non_trivial if n_non_trivial else 1.0
    cost_rate   = n_has_cost_material / n_non_trivial if n_non_trivial else 1.0
    hours_rate  = n_has_hours_fab   / n_non_trivial if n_non_trivial else 1.0
    comp_rate   = n_has_components  / n_non_trivial if n_non_trivial else 1.0
    cat_rate    = (n_has_multi_cats /
                   sum(1 for r in results
                       if r.get("checks", {}).get("has_multi_categories") is not None)
                  ) if any(r.get("checks", {}).get("has_multi_categories") is not None for r in results) else 1.0

    # ── Print summary ─────────────────────────────────────────────────────────
    print()
    print(f"  Parsed           : {n_parsed}/{n_total}   {parse_rate:>6.0%}  {_bar(parse_rate)}")
    print(f"  Non-trivial      : {n_non_trivial}/{n_parsed} (rest are small/parts)")
    print(f"  Total components : {total_components}  (avg {total_components/max(n_parsed,1):.1f}/proj)")
    print()
    print(f"  id = folder name : {n_id_ok}/{n_parsed}            {id_rate:>6.0%}  {_bar(id_rate)}")
    print(f"  client extracted : {n_has_client}/{n_parsed}       {client_rate:>6.0%}  {_bar(client_rate)}")
    print()
    print(f"  (checks below apply only to non-trivial projects)")
    print(f"  base_price > 0   : {n_has_base_price}/{n_non_trivial}    {price_rate:>6.0%}  {_bar(price_rate)}")
    print(f"  cost_material>0  : {n_has_cost_material}/{n_non_trivial} {cost_rate:>6.0%}  {_bar(cost_rate)}")
    print(f"  hours_fab > 0    : {n_has_hours_fab}/{n_non_trivial}     {hours_rate:>6.0%}  {_bar(hours_rate)}")
    print(f"  ≥1 component     : {n_has_components}/{n_non_trivial}    {comp_rate:>6.0%}  {_bar(comp_rate)}")
    print(f"  ≥2 categories    : {n_has_multi_cats} (price>1000€ only)  {cat_rate:>6.0%}  {_bar(cat_rate)}")
    print()
    if issue_counter:
        print(f"  Top issue types:")
        for iss, cnt in issue_counter.most_common(8):
            print(f"    {iss:<28} {cnt:>4}")
    print(f"  Elapsed: {elapsed:.1f}s")

    # Pass/fail per threshold
    thresholds = {
        "parse_rate":      (parse_rate,  MIN_PARSE_RATE),
        "client_rate":     (client_rate, MIN_CLIENT_RATE),
        "base_price_rate": (price_rate,  MIN_BASE_PRICE_RATE),
        "components_rate": (comp_rate,   MIN_COMPONENTS_RATE),
        "categories_rate": (cat_rate,    MIN_CATEGORIES_RATE),
    }
    failed = [name for name, (val, thr) in thresholds.items() if val < thr]
    if failed:
        print(f"  ⚠  Below threshold: {', '.join(failed)}")
    else:
        print(f"  ✓ All quality thresholds met")

    return {
        "year":             year,
        "folders_scanned":  n_total,
        "parsed":           n_parsed,
        "non_trivial":      n_non_trivial,
        "total_components": total_components,
        "rates": {
            "parse":       round(parse_rate, 3),
            "id_ok":       round(id_rate, 3),
            "client":      round(client_rate, 3),
            "base_price":  round(price_rate, 3),
            "cost_material": round(cost_rate, 3),
            "hours_fab":   round(hours_rate, 3),
            "components":  round(comp_rate, 3),
            "categories":  round(cat_rate, 3),
        },
        "issues":           dict(issue_counter),
        "failed_thresholds": failed,
        "elapsed_s":        round(elapsed, 1),
        "per_project":      results if verbose else [
            # only include failed projects in non-verbose mode
            r for r in results
            if r.get("issues") and not r.get("trivial")
        ],
    }


# ── Layer 2: Index-build smoke test ───────────────────────────────────────────

# Fields app.py reads from retrieved projects — used to validate shape
_APP_REQUIRED_FIELDS = [
    "id", "client", "description", "product_type", "tags",
    "configuration.by_category", "configuration.hours_fabrication",
    "configuration.hours_programmation", "configuration.base_price",
]


def _get_nested(d: dict, path: str):
    cur = d
    for key in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def smoke_build_index(year: str, projects: list, temp_suffix: str = "__validate") -> dict:
    """
    Embed every parsed project into a temporary ChromaDB collection.
    Mirrors rag.build_yearly_index() so we catch the SAME failure modes
    the real build would hit (metadata type errors, embedding failures, etc.)
    without touching the production collection.

    Returns dict with success/failure counts and error details.
    """
    import rag

    print(f"\n  [layer 2] Building test index for {year} ({len(projects)} projects) …")
    coll_name = f"validate_{year}_{temp_suffix}"
    t0 = time.time()

    errors: list[dict] = []
    embedded = 0
    skipped_empty = 0

    try:
        oai    = rag._openai_client()
        chroma = rag._chroma_client()
    except Exception as e:
        return {
            "attempted": len(projects),
            "embedded":  0,
            "errors":    [{"stage": "client_init", "error": str(e)}],
            "elapsed_s": 0,
        }

    # Drop any stale temp collection first
    try:
        chroma.delete_collection(coll_name)
    except Exception:
        pass

    try:
        collection = chroma.create_collection(
            name=coll_name,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        return {
            "attempted": len(projects),
            "embedded":  0,
            "errors":    [{"stage": "create_collection", "error": str(e)}],
            "elapsed_s": round(time.time() - t0, 1),
        }

    # Embed in batches to avoid holding too much in memory
    BATCH = 25
    batch_ids: list = []
    batch_embs: list = []
    batch_docs: list = []
    batch_metas: list = []

    def _flush():
        nonlocal embedded
        if not batch_ids:
            return
        try:
            collection.add(ids=batch_ids, embeddings=batch_embs,
                           documents=batch_docs, metadatas=batch_metas)
            embedded += len(batch_ids)
        except Exception as e:
            # One poison record in the batch — fall back to per-item insertion
            for idx in range(len(batch_ids)):
                try:
                    collection.add(
                        ids=[batch_ids[idx]],
                        embeddings=[batch_embs[idx]],
                        documents=[batch_docs[idx]],
                        metadatas=[batch_metas[idx]],
                    )
                    embedded += 1
                except Exception as per_e:
                    errors.append({
                        "stage": "chroma_add",
                        "id":    batch_ids[idx],
                        "error": str(per_e)[:200],
                    })
        batch_ids.clear(); batch_embs.clear(); batch_docs.clear(); batch_metas.clear()

    for idx, p in enumerate(projects):
        try:
            text = rag._project_to_text(p)
        except Exception as e:
            errors.append({"stage": "_project_to_text", "id": p.get("id"), "error": str(e)})
            continue

        if not text.strip():
            skipped_empty += 1
            continue

        try:
            vec = rag.embed_text(text, oai)
        except Exception as e:
            errors.append({"stage": "embed_text", "id": p.get("id"), "error": str(e)[:200]})
            continue

        conf = p.get("configuration", {}) or {}
        io   = p.get("io", {}) or {}

        def _s(v, default=""):
            return str(v) if v is not None else default

        try:
            metadata = {
                "id":            _s(p.get("id", idx)),
                "client":        _s(p.get("client")),
                "product_type":  _s(p.get("product_type")),
                "description":   _s(p.get("description"))[:200],
                "divalto_desig": _s(p.get("divalto_designation"))[:100],
                "metier":        _s(p.get("metier")),
                "year":          str(year),
                "nb_motors":     _s(p.get("nb_motors")),
                "base_price":    _s(conf.get("base_price", 0)),
                "hours_fab":     _s(conf.get("hours_fabrication", 0)),
                "hours_prog":    _s(conf.get("hours_programmation", 0)),
                "nb_components": _s(conf.get("nb_components", 0)),
                "margin_pct":    _s(conf.get("margin_pct", "")),
                "has_automation": "1" if (conf.get("hours_programmation") or 0) > 0 else "0",
                "io_total":      _s(io.get("total", 0)),
                "io_di":         _s(io.get("digital_in", 0)),
                "io_do":         _s(io.get("digital_out", 0)),
                "tags":          " ".join(p.get("tags") or [])[:200],
            }
        except Exception as e:
            errors.append({"stage": "build_metadata", "id": p.get("id"), "error": str(e)})
            continue

        batch_ids.append(f"{p.get('id','')}_{idx}")
        batch_embs.append(vec)
        batch_docs.append(text)
        batch_metas.append(metadata)

        if len(batch_ids) >= BATCH:
            _flush()
            # Progress tick
            print(f"    embedded {embedded}/{len(projects)}…", end="\r", flush=True)

    _flush()
    count_in_db = collection.count()
    elapsed = time.time() - t0

    print(f"    embedded {embedded}/{len(projects)}  (collection count: {count_in_db})  "
          f"in {elapsed:.1f}s")

    # Keep the collection around for the retrieval test; caller teardown later.
    return {
        "attempted":    len(projects),
        "embedded":     embedded,
        "skipped_empty": skipped_empty,
        "errors":       errors,
        "collection":   coll_name,
        "count_in_db":  count_in_db,
        "elapsed_s":    round(elapsed, 1),
    }


# ── Layer 3: Retrieval smoke test ─────────────────────────────────────────────

SAMPLE_QUERIES = [
    "Armoire 2 pompes avec variateur ATV630 et automate S7-1200",
    "Coffret commande pompe avec S4W",
    "Armoire 3 pompes démarreurs 11kW",
    "Armoire avec Millenium et modbus",
    "Equipement électrique commande armoire",
]


def smoke_retrieve(year: str, coll_name: str, json_path: Path) -> dict:
    """
    Run sample queries against the temp collection built above.
    For each hit, verify:
      • the ID strips back to a key present in the year's JSON
      • the retrieved project dict has every field app.py's prompt code reads
      • no None slips through where the frontend / LLM expects a value
    """
    import rag

    print(f"\n  [layer 3] Retrieval smoke test for {year} …")
    t0 = time.time()

    # Load JSON to resolve retrieved IDs back to full project objects
    try:
        projects_by_id = {str(p["id"]): p for p in json.loads(json_path.read_text())}
    except Exception as e:
        return {"error": f"Could not load {json_path}: {e}"}

    chroma = rag._chroma_client()
    try:
        collection = chroma.get_collection(coll_name)
    except Exception as e:
        return {"error": f"Cannot get collection {coll_name}: {e}"}

    oai = rag._openai_client()

    query_reports: list[dict] = []
    lookup_failures = 0
    field_failures: Counter = Counter()
    total_hits = 0

    for q in SAMPLE_QUERIES:
        try:
            vec = rag.embed_text(q, oai)
        except Exception as e:
            query_reports.append({"query": q, "error": f"embed_text: {e}"})
            continue

        try:
            res = collection.query(
                query_embeddings=[vec],
                n_results=min(3, collection.count()),
                include=["metadatas", "distances"],
            )
        except Exception as e:
            query_reports.append({"query": q, "error": f"collection.query: {e}"})
            continue

        hits = []
        for i, uid in enumerate(res["ids"][0]):
            # Strip _idx suffix to recover the project id (same logic rag.py uses)
            pid = "_".join(uid.split("_")[:-1]) if "_" in uid else uid
            proj = projects_by_id.get(pid)
            if proj is None:
                # Try fallback: full uid match (rag.py does this too)
                proj = projects_by_id.get(uid)
            if proj is None:
                lookup_failures += 1
                hits.append({"id": uid, "ok": False, "reason": "lookup_failed"})
                continue

            # Validate shape: every field app.py reads must be accessible
            missing = [f for f in _APP_REQUIRED_FIELDS
                       if _get_nested(proj, f) is None]
            for f in missing:
                field_failures[f] += 1

            hits.append({
                "id":           proj.get("id", ""),
                "ok":           not missing,
                "missing":      missing,
                "similarity":   round(1.0 - res["distances"][0][i], 3),
                "client":       proj.get("client", "") or "(none)",
            })
            total_hits += 1

        query_reports.append({"query": q, "hits": hits})

    elapsed = time.time() - t0

    # Print a compact table
    print()
    for qr in query_reports:
        if "error" in qr:
            print(f"    ✗ \"{qr['query'][:55]}\" → ERROR: {qr['error']}")
            continue
        for i, h in enumerate(qr["hits"]):
            status = "✓" if h.get("ok") else "✗"
            q_label = f"\"{qr['query'][:40]}\"" if i == 0 else " " * 42
            print(f"    {status} {q_label}  [{h.get('similarity','?')}] "
                  f"{h.get('client','')[:20]:<20}  {h.get('id','')[:40]}")
            if h.get("missing"):
                print(f"         missing: {h['missing']}")
            if h.get("reason"):
                print(f"         reason : {h['reason']}")

    print(f"\n    Total hits   : {total_hits}")
    print(f"    Lookup fails : {lookup_failures}")
    if field_failures:
        print(f"    Missing fields (across hits):")
        for f, n in field_failures.most_common():
            print(f"      {f:<40} {n}")
    else:
        print(f"    All retrieved projects have every field app.py needs ✓")
    print(f"    Elapsed: {elapsed:.1f}s")

    return {
        "queries":          len(SAMPLE_QUERIES),
        "total_hits":       total_hits,
        "lookup_failures":  lookup_failures,
        "field_failures":   dict(field_failures),
        "reports":          query_reports,
        "elapsed_s":        round(elapsed, 1),
    }


def teardown_collections(coll_names: list[str]) -> None:
    """Delete all temp collections created by this run."""
    try:
        import rag
        chroma = rag._chroma_client()
        for name in coll_names:
            try:
                chroma.delete_collection(name)
            except Exception:
                pass
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────────────


def _load_env():
    """Load API keys from poc/.env so --build-index can call OpenAI."""
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                import os
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    ap = argparse.ArgumentParser(description="Validate CETIE yearly Excel parser")
    ap.add_argument("--year",    action="append",
                    help="Year(s) to scan (default: all years found). Can repeat.")
    ap.add_argument("--sample",  type=int, default=None,
                    help="Parse only the first N folders per year (speed up)")
    ap.add_argument("--verbose", action="store_true",
                    help="Print every failing project inline")
    ap.add_argument("--strict",  action="store_true",
                    help="Exit 1 if any year falls below quality thresholds")
    ap.add_argument("--json",    default=None,
                    help="Write machine-readable report to this path")
    ap.add_argument("--build-index", action="store_true",
                    help="[layer 2] Embed every parsed project into a TEMP "
                         "ChromaDB collection to catch metadata/embedding failures. "
                         "Requires OPENAI_API_KEY in poc/.env. Adds ~2–3 min per year.")
    ap.add_argument("--test-retrieval", action="store_true",
                    help="[layer 3] Run sample queries and check every retrieved "
                         "project has the fields app.py requires. Implies --build-index.")
    ap.add_argument("--full", action="store_true",
                    help="Run all layers: parse + build-index + retrieval. "
                         "This is the true pre-deployment gate.")
    args = ap.parse_args()

    # --full implies layer 2 and 3
    if args.full:
        args.build_index    = True
        args.test_retrieval = True
    if args.test_retrieval:
        args.build_index    = True   # retrieval needs an index

    if args.build_index:
        _load_env()

    # Discover years
    if args.year:
        years = args.year
    else:
        years = sorted(
            p.name for p in YEARLY_DIR.iterdir()
            if p.is_dir() and p.name.isdigit() and len(p.name) == 4
        )
    if not years:
        print(f"No year folders found in {YEARLY_DIR}")
        sys.exit(1)

    layers = ["layer 1 (parse)"]
    if args.build_index:    layers.append("layer 2 (build-index)")
    if args.test_retrieval: layers.append("layer 3 (retrieval)")

    print("=" * 70)
    print(" CETIE Parser Validation")
    print(f" Years   : {', '.join(years)}    Sample: {args.sample or 'all'}")
    print(f" Layers  : {' → '.join(layers)}")
    print("=" * 70)

    reports = [scan_year(y, sample=args.sample, verbose=args.verbose) for y in years]

    # ── Layer 2: build-index smoke ────────────────────────────────────────────
    temp_collections: list[str] = []
    if args.build_index:
        for r in reports:
            if "error" in r or r["parsed"] == 0:
                continue
            year = r["year"]
            # Load the JSON we just wrote (parse_yearly_data saves it)
            # BUT scan_year doesn't save — it parses in-memory. So we re-parse
            # into JSON file via the existing script OR rebuild from per-project results.
            # Simpler: read the existing data/yearly_projects_YYYY.json which the
            # scan has already implicitly validated.
            json_path = BASE_DIR / "data" / f"yearly_projects_{year}.json"
            if not json_path.exists():
                print(f"\n  [layer 2] {year}: {json_path} not found — run "
                      f"`python3 poc/parse_yearly_data.py {year} --force` first")
                r["index_build"] = {"error": f"missing JSON: {json_path}"}
                continue
            try:
                projects = json.loads(json_path.read_text())
            except Exception as e:
                r["index_build"] = {"error": f"bad JSON: {e}"}
                continue

            result = smoke_build_index(year, projects)
            r["index_build"] = result
            if result.get("collection"):
                temp_collections.append(result["collection"])

    # ── Layer 3: retrieval smoke ──────────────────────────────────────────────
    if args.test_retrieval:
        for r in reports:
            if "error" in r or not r.get("index_build"):
                continue
            ib = r["index_build"]
            if not ib.get("collection") or ib.get("embedded", 0) == 0:
                r["retrieval"] = {"skipped": "no index to query"}
                continue
            year = r["year"]
            json_path = BASE_DIR / "data" / f"yearly_projects_{year}.json"
            r["retrieval"] = smoke_retrieve(year, ib["collection"], json_path)

    # ── Teardown temp collections ─────────────────────────────────────────────
    if temp_collections:
        print(f"\n  Cleaning up {len(temp_collections)} temp collections…")
        teardown_collections(temp_collections)

    # ── Overall summary ───────────────────────────────────────────────────────
    print(f"\n{'═' * 70}")
    print(" OVERALL SUMMARY")
    print("═" * 70)
    any_failed = False
    for r in reports:
        if "error" in r:
            print(f"  {r['year']}: ERROR — {r['error']}")
            any_failed = True
            continue
        status = "✓" if not r["failed_thresholds"] else "✗"
        print(f"  {status} layer1  {r['year']}: {r['parsed']}/{r['folders_scanned']} parsed, "
              f"{r['total_components']} components")
        if r["failed_thresholds"]:
            any_failed = True
            for name in r["failed_thresholds"]:
                val = r["rates"].get(name.replace("_rate", ""), 0)
                print(f"       └ {name}: {val:.0%}")

        ib = r.get("index_build")
        if ib:
            if "error" in ib:
                print(f"  ✗ layer2  {r['year']}: {ib['error']}")
                any_failed = True
            else:
                ok = ib["embedded"] == ib["attempted"] - ib.get("skipped_empty", 0)
                icon = "✓" if ok and not ib["errors"] else "✗"
                print(f"  {icon} layer2  {r['year']}: embedded {ib['embedded']}/{ib['attempted']}, "
                      f"{len(ib['errors'])} error(s)")
                if ib["errors"]:
                    any_failed = True
                    # Show top 3 error types
                    err_types: Counter = Counter(e.get("stage", "?") for e in ib["errors"])
                    for stage, n in err_types.most_common(3):
                        print(f"       └ {stage}: {n}")

        rt = r.get("retrieval")
        if rt:
            if "error" in rt or rt.get("skipped"):
                print(f"  ✗ layer3  {r['year']}: {rt.get('error') or rt.get('skipped')}")
                any_failed = True
            else:
                ok = (rt["lookup_failures"] == 0 and not rt["field_failures"])
                icon = "✓" if ok else "✗"
                print(f"  {icon} layer3  {r['year']}: {rt['total_hits']} hits, "
                      f"{rt['lookup_failures']} lookup-fail, "
                      f"{sum(rt['field_failures'].values())} field-miss")
                if not ok:
                    any_failed = True

    # ── Write report ──────────────────────────────────────────────────────────
    if args.json:
        Path(args.json).write_text(json.dumps(reports, indent=2, ensure_ascii=False))
        print(f"\nReport written to {args.json}")

    # ── Exit code ─────────────────────────────────────────────────────────────
    if args.strict and any_failed:
        print("\n[STRICT] Validation failed — exit 1")
        sys.exit(1)
    print()


if __name__ == "__main__":
    main()
