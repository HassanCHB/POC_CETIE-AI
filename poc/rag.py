"""
RAG module for CETIE POC
Handles embedding of historical quotes and semantic retrieval using:
  - OpenAI text-embedding-3-small  (embeddings)
  - ChromaDB                        (vector store, persisted to disk)

Two collections:
  - historical_quotes   : manually curated example quotes (from data/historical_quotes.json)
  - yearly_projects_YYYY: real parsed DEVIS projects (from data/yearly_projects_YYYY.json)
"""

import os
import math
import json
import glob
import threading
import chromadb
from datetime import datetime
from openai import OpenAI

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(__file__)
QUOTES_PATH = os.path.join(BASE_DIR, "data", "historical_quotes.json")
COLLECTION  = "historical_quotes"
YEARLY_COLLECTION_PREFIX = "yearly_projects_"

# ChromaDB storage location.
# In production (Render) we point this at /var/cetie-state/chroma_db so the
# index lives on the persistent disk — survives every deploy, doesn't bloat
# the git repo, doesn't run into GitHub's 100 MB file limit.
# Locally, falls back to poc/chroma_db so dev work keeps working unchanged.
_DEFAULT_CHROMA = os.path.join(BASE_DIR, "chroma_db")
CHROMA_PATH = os.environ.get("CETIE_CHROMA_DIR") or _DEFAULT_CHROMA
try:
    os.makedirs(CHROMA_PATH, exist_ok=True)
except Exception as _e:
    print(f"[rag] Could not create {CHROMA_PATH}: {_e} — falling back to {_DEFAULT_CHROMA}")
    CHROMA_PATH = _DEFAULT_CHROMA
print(f"[rag] ChromaDB storage path: {CHROMA_PATH}")

# ── Retrieval tuning ─────────────────────────────────────────────────────────
# Temporal decay: recent projects are more relevant for pricing and component
# references (parts get discontinued, prices drift, automation platforms evolve).
# Half-life for decay = 0.15 → ~4.6 years (a 2022 project scores ~0.55,
# a 2018 project ~0.30, a 2026 project 1.00).
#
# Final score = SEMANTIC_WEIGHT * cosine_sim + TEMPORAL_WEIGHT * temporal_decay
# Must sum to 1.0.
TEMPORAL_DECAY_CONSTANT = 0.15   # tune based on eval results
TEMPORAL_WEIGHT         = 0.35
SEMANTIC_WEIGHT         = 0.65
assert abs(TEMPORAL_WEIGHT + SEMANTIC_WEIGHT - 1.0) < 1e-9


def _temporal_score(project_year, current_year: int | None = None) -> float:
    """
    Exponential-decay score rewarding recent projects.

    Accepts year as int, str, or None. Unknown / malformed year → neutral 0.5.

    Half-life ≈ 4.6 years with default decay constant 0.15:
      2026 → 1.00   2024 → 0.74   2022 → 0.55
      2020 → 0.41   2018 → 0.30   2017 → 0.22
    """
    if project_year is None or project_year == "":
        return 0.5
    try:
        y = int(str(project_year)[:4])
    except (ValueError, TypeError):
        return 0.5
    if current_year is None:
        current_year = datetime.now().year
    age = max(0, current_year - y)
    return math.exp(-TEMPORAL_DECAY_CONSTANT * age)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _openai_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in environment / .env")
    return OpenAI(api_key=api_key)


# ── ChromaDB singleton ────────────────────────────────────────────────────────
# One PersistentClient per worker process is enough — SQLite can't handle
# multiple concurrent writers, and each extra client adds a file-lock round trip.
# With Gunicorn's multi-process model each worker has its own copy of this module,
# so this singleton is per-worker (correct behaviour).
_chroma_instance: chromadb.PersistentClient | None = None
_chroma_lock = threading.Lock()


def _chroma_client() -> chromadb.PersistentClient:
    """Return the module-level ChromaDB singleton (created once per worker)."""
    global _chroma_instance
    if _chroma_instance is None:
        with _chroma_lock:
            if _chroma_instance is None:          # double-checked locking
                _chroma_instance = chromadb.PersistentClient(path=CHROMA_PATH)
    return _chroma_instance


def embed_text(text: str, client=None) -> list[float]:
    """Embed a single string with text-embedding-3-small.

    A hard 15-second timeout is enforced so a transient OpenAI network blip
    never hangs a Gunicorn worker until it gets SIGKILL'd (default 180 s).
    """
    if client is None:
        client = _openai_client()
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text.replace("\n", " "),
        timeout=15.0,   # prevent infinite hang on network blip
    )
    return response.data[0].embedding


def _quote_to_text(quote: dict) -> str:
    """Convert a historical quote dict into a single embeddable string."""
    parts = [
        quote.get("customer_request", ""),
        quote.get("product_type", ""),
        quote.get("summary", ""),
        quote.get("sector", ""),
        " ".join(quote.get("tags", [])),
    ]
    return " ".join(p for p in parts if p).strip()


def _project_to_text(project: dict) -> str:
    """
    Legacy single-vector representation — kept for backwards compat (eval scripts
    that still call _project_to_text directly). In production we now embed THREE
    separate chunks per project via _project_to_chunks(), so this function just
    concatenates those chunks for callers that still expect one string.
    """
    chunks = _project_to_chunks(project)
    return " ".join(c["text"] for c in chunks if c["text"]).strip()


# Chunk types (kept stable so ChromaDB ids stay consistent across reindexes)
CHUNK_SUMMARY = "summary"   # application context: what the client asked for
CHUNK_PARAMS  = "params"    # quantitative profile: hours, motors, price, automation
CHUNK_BOM     = "bom"       # bill of materials: real component selections by category

# Which 5 categories carry the most diagnostic BoM signal for retrieval.
# Ordered by importance: enclosure + power + automation dominate price & hours,
# door controls + supplied_separately catch the accessory-heavy projects.
BOM_CHUNK_CATEGORIES = [
    "01_cabinet_enclosure",
    "04_internal_chassis_power",
    "04_internal_chassis_automation",
    "06_door_controls",
    "07_supplied_separately",
]


def _project_to_chunks(project: dict) -> list[dict]:
    """
    Split one project into 3 targeted embedding chunks, each stored as a
    distinct ChromaDB document with compound id {project_id}_{chunk_type}.

    Why three chunks and not one:
      - A BoM-specific query ("GV2-P10 + LC1-D09 + ATV630") matches the bom
        chunk strongly regardless of description wording.
      - A parameter-heavy query ("2 pompes 7.5kW variateur Siemens") matches
        the params chunk.
      - A free-text application query matches the summary chunk.
    A project hit via ANY chunk surfaces once (see _deduplicate_by_project).
    """
    conf = project.get("configuration", {}) or {}
    cats = conf.get("by_category", {}) or {}

    # ── Chunk 1: Application summary ────────────────────────────────────────
    # What the client asked for + product classification + free-text tags
    summary_parts = [
        (project.get("client_request") or "")[:600],
        project.get("description") or "",
        project.get("divalto_designation") or "",
        project.get("product_type") or "",
        project.get("metier") or "",
        " ".join(project.get("tags") or []),
    ]
    chunk_summary = " ".join(p for p in summary_parts if p).strip()

    # ── Chunk 2: Technical parameters (quantitative + architecture) ─────────
    params_parts = [
        project.get("product_type") or "",
        project.get("metier") or "",
    ]
    if project.get("nb_motors"):
        params_parts.append(f"{project['nb_motors']} moteurs")
    h_fab  = conf.get("hours_fabrication",  0) or 0
    h_prog = conf.get("hours_programmation", 0) or 0
    if h_fab:  params_parts.append(f"câblage {h_fab}h")
    if h_prog: params_parts.append(f"automatisme {h_prog}h")
    price  = conf.get("base_price", 0) or 0
    if price: params_parts.append(f"{int(price)}EUR")

    io = project.get("io", {}) or {}
    if io.get("total", 0) > 0:
        params_parts.append(
            f"{io.get('digital_in', 0)}DI {io.get('digital_out', 0)}DO "
            f"{io.get('analog_in', 0)}AI {io.get('analog_out', 0)}AO"
        )

    # Automation platform signature from BoM
    auto_items = cats.get("04_internal_chassis_automation", []) or []
    if auto_items:
        params_parts.append(" ".join(
            (it.get("designation") or "")[:80] for it in auto_items[:4]
        ))

    # architecture_text already captures category-structure + tech keywords
    arch = project.get("architecture_text") or ""
    if arch:
        params_parts.append(arch)

    chunk_params = " ".join(p for p in params_parts if p).strip()

    # ── Chunk 3: BoM components (by category, real designations) ────────────
    bom_lines = [project.get("product_type") or ""]
    for cat in BOM_CHUNK_CATEGORIES:
        items = cats.get(cat, []) or []
        if not items:
            continue
        desigs = [
            (it.get("designation") or "").strip()
            for it in items[:6]
            if it.get("designation")
        ]
        if desigs:
            bom_lines.append(f"{cat}: " + " | ".join(desigs))
    chunk_bom = " ".join(p for p in bom_lines if p).strip()

    return [
        {"chunk_type": CHUNK_SUMMARY, "text": chunk_summary},
        {"chunk_type": CHUNK_PARAMS,  "text": chunk_params},
        {"chunk_type": CHUNK_BOM,     "text": chunk_bom},
    ]


def _deduplicate_by_project(hits: list[dict]) -> list[dict]:
    """
    Multiple chunks from the same project may appear in results — keep only
    the HIGHEST-scoring chunk per project_id and sort by final score.
    """
    best: dict[str, dict] = {}
    for h in hits:
        pid = h.get("project_id") or h.get("id", "")
        if pid not in best or h.get("similarity_score", 0) > best[pid].get("similarity_score", 0):
            best[pid] = h
    return sorted(best.values(), key=lambda x: x.get("similarity_score", 0), reverse=True)


# ── Index management ───────────────────────────────────────────────────────────

def is_index_ready() -> bool:
    """Return True if the ChromaDB collection exists and is non-empty."""
    try:
        col = _chroma_client().get_collection(COLLECTION)
        return col.count() > 0
    except Exception:
        return False


def build_index(force: bool = False) -> None:
    """
    Embed all historical quotes and store in ChromaDB.
    Skips if already indexed unless force=True.
    """
    if is_index_ready() and not force:
        print("[RAG] Index already built – skipping.")
        return

    print("[RAG] Building index from historical quotes …")
    with open(QUOTES_PATH, encoding="utf-8") as f:
        quotes: list[dict] = json.load(f)

    oai    = _openai_client()
    chroma = _chroma_client()

    # Drop and recreate collection for a clean index
    try:
        chroma.delete_collection(COLLECTION)
    except Exception:
        pass

    collection = chroma.create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    ids, embeddings, documents, metadatas = [], [], [], []

    for q in quotes:
        text = _quote_to_text(q)
        vec  = embed_text(text, oai)

        ids.append(str(q["id"]))
        embeddings.append(vec)
        documents.append(text)
        metadatas.append({
            "id":           str(q["id"]),
            "product_type": q.get("product_type", ""),
            "sector":       q.get("sector", ""),
            "summary":      q.get("summary", ""),
        })

    collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    print(f"[RAG] Index built – {len(ids)} quotes embedded.")


# ── Retrieval ──────────────────────────────────────────────────────────────────

def retrieve_similar(query_text: str, n_results: int = 3) -> list[dict]:
    """
    Find the N most similar historical quotes to query_text.
    Returns a list of full quote dicts enriched with a similarity_score (0–1).
    Returns [] if the index is empty or an error occurs.
    """
    if not is_index_ready():
        print("[RAG] Index not ready – skipping retrieval.")
        return []

    try:
        oai        = _openai_client()
        chroma     = _chroma_client()
        collection = chroma.get_collection(COLLECTION)

        query_vec = embed_text(query_text, oai)

        # Fetch wider so temporal re-ranking has candidates to promote
        fetch_n = min(max(n_results * 3, n_results), collection.count())
        results = collection.query(
            query_embeddings=[query_vec],
            n_results=fetch_n,
            include=["metadatas", "distances"],
        )

        # Load full quote objects (they may include a "year" field)
        with open(QUOTES_PATH, encoding="utf-8") as f:
            quotes_by_id = {str(q["id"]): q for q in json.load(f)}

        scored = []
        for i, qid in enumerate(results["ids"][0]):
            quote  = dict(quotes_by_id.get(qid, {}))
            cosine = 1.0 - results["distances"][0][i]
            # Historical quotes may not carry a year — _temporal_score handles None
            temp = _temporal_score(quote.get("year") or quote.get("date", "")[:4])
            final = SEMANTIC_WEIGHT * cosine + TEMPORAL_WEIGHT * temp
            quote["similarity_score"] = round(final, 3)
            quote["cosine_score"]     = round(cosine, 3)
            quote["temporal_score"]   = round(temp, 3)
            scored.append(quote)

        # Re-rank and trim to requested n_results
        scored.sort(key=lambda x: x["similarity_score"], reverse=True)
        return scored[:n_results]

    except Exception as e:
        print(f"[RAG] Retrieval error: {e}")
        return []


# ── Yearly projects index ──────────────────────────────────────────────────────

def _yearly_collection_name(year: str) -> str:
    return f"{YEARLY_COLLECTION_PREFIX}{year}"


def _yearly_projects_path(year: str) -> str:
    return os.path.join(BASE_DIR, "data", f"yearly_projects_{year}.json")


def is_yearly_index_ready(year: str = "2022") -> bool:
    """Return True if the yearly ChromaDB collection exists and is non-empty."""
    try:
        col = _chroma_client().get_collection(_yearly_collection_name(year))
        return col.count() > 0
    except Exception:
        return False


def build_yearly_index(year: str = "2022", force: bool = False) -> None:
    """
    Embed all yearly DEVIS projects and store in ChromaDB.
    Requires: poc/data/yearly_projects_{year}.json (run parse_yearly_data.py first).
    Skips if already indexed unless force=True.
    """
    coll_name   = _yearly_collection_name(year)
    data_path   = _yearly_projects_path(year)

    if is_yearly_index_ready(year) and not force:
        print(f"[RAG] Yearly index '{coll_name}' already built — skipping.")
        return

    if not os.path.exists(data_path):
        print(f"[RAG] Yearly projects file not found: {data_path}")
        print("[RAG] Run: python3 poc/parse_yearly_data.py first.")
        return

    print(f"[RAG] Building yearly index '{coll_name}' …")
    with open(data_path, encoding="utf-8") as f:
        projects: list[dict] = json.load(f)

    oai    = _openai_client()
    chroma = _chroma_client()

    try:
        chroma.delete_collection(coll_name)
    except Exception:
        pass

    collection = chroma.create_collection(
        name=coll_name,
        metadata={"hnsw:space": "cosine"},
    )

    # Batched incremental add — avoids the long-delay race condition where
    # ChromaDB loses track of an empty newly-created collection after many
    # minutes of OpenAI embedding calls.
    BATCH_SIZE = 60   # ≈ 20 projects × 3 chunks; small enough to add frequently
    batch_ids:   list = []
    batch_embs:  list = []
    batch_docs:  list = []
    batch_metas: list = []
    total_added = 0

    def _flush_batch():
        nonlocal total_added, batch_ids, batch_embs, batch_docs, batch_metas, collection
        if not batch_ids:
            return
        try:
            collection.add(ids=batch_ids, embeddings=batch_embs,
                           documents=batch_docs, metadatas=batch_metas)
        except Exception as e:
            # Re-fetch the collection and retry once (handles ChromaDB's
            # occasional stale-handle error after long embedding delays)
            print(f"    [WARN] collection.add failed ({e}) — re-fetching and retrying…")
            collection = chroma.get_or_create_collection(
                name=coll_name, metadata={"hnsw:space": "cosine"})
            collection.add(ids=batch_ids, embeddings=batch_embs,
                           documents=batch_docs, metadatas=batch_metas)
        total_added += len(batch_ids)
        batch_ids.clear(); batch_embs.clear()
        batch_docs.clear(); batch_metas.clear()

    def _s(v, default=""):
        """Convert any value to a safe string for ChromaDB metadata."""
        return str(v) if v is not None else default

    skipped = 0
    for idx, p in enumerate(projects):
        conf = p.get("configuration", {}) or {}
        io   = p.get("io", {}) or {}

        # Build per-project base metadata once — shared across all 3 chunks
        base_meta = {
            "project_id":       _s(p.get("id", idx)),
            "client":           _s(p.get("client")),
            "product_type":     _s(p.get("product_type")),
            "description":      _s(p.get("description"))[:200],
            "divalto_desig":    _s(p.get("divalto_designation"))[:100],
            "metier":           _s(p.get("metier")),
            "year":             str(year),
            "nb_motors":        _s(p.get("nb_motors")),
            "base_price":       _s(conf.get("base_price", 0)),
            "hours_fab":        _s(conf.get("hours_fabrication", 0)),
            "hours_prog":       _s(conf.get("hours_programmation", 0)),
            "nb_components":    _s(conf.get("nb_components", 0)),
            "margin_pct":       _s(conf.get("margin_pct", "")),
            "has_automation":   "1" if (conf.get("hours_programmation") or 0) > 0 else "0",
            "io_total":         _s(io.get("total", 0)),
            "io_di":            _s(io.get("digital_in", 0)),
            "io_do":            _s(io.get("digital_out", 0)),
            "tags":             " ".join(p.get("tags", []) or [])[:200],
        }

        # Emit one ChromaDB document per chunk (3 per project typically)
        for chunk in _project_to_chunks(p):
            text = chunk["text"]
            if not text.strip():
                continue
            # Unique id = {project_id}_{idx}_{chunk_type} — unique across repeats
            chunk_id = f"{p['id']}_{idx}_{chunk['chunk_type']}"
            try:
                vec = embed_text(text, oai)
            except Exception as e:
                print(f"    [WARN] embed failed for {chunk_id}: {e}")
                skipped += 1
                continue
            batch_ids.append(chunk_id)
            batch_embs.append(vec)
            batch_docs.append(text)
            batch_metas.append({**base_meta, "chunk_type": chunk["chunk_type"]})

            if len(batch_ids) >= BATCH_SIZE:
                _flush_batch()

        # Progress feedback (every 25 projects)
        if (idx + 1) % 25 == 0:
            print(f"    added {total_added + len(batch_ids)} chunks / {idx+1}/{len(projects)} projects…")

    _flush_batch()  # final partial batch

    if total_added:
        # Recount for confidence — tells us what's actually persisted in ChromaDB
        try:
            persisted = collection.count()
        except Exception:
            persisted = total_added
        print(f"[RAG] Yearly index built — {persisted} chunks persisted "
              f"(≈ {persisted / max(len(projects), 1):.1f} chunks / project avg)"
              + (f"  [{skipped} chunks skipped]" if skipped else ""))
    else:
        print("[RAG] No projects to embed.")


def retrieve_similar_projects(query_text: str, year: str = "2022", n_results: int = 5) -> list[dict]:
    """
    Find the N most similar yearly DEVIS projects to query_text.

    Returns list of project dicts enriched with:
      - similarity_score: final combined score (semantic × recency)
      - cosine_score:     raw cosine similarity (for diagnostics)
      - temporal_score:   year-decay weight (for diagnostics)
      - matched_chunk:    which of the 3 chunks (summary/params/bom) was best

    Fetches n_results × 4 raw hits, re-ranks with temporal decay, deduplicates
    so each project appears at most once even if multiple of its chunks hit,
    and returns the top n_results.
    """
    if not is_yearly_index_ready(year):
        print(f"[RAG] Yearly index for {year} not ready — skipping.")
        return []

    try:
        oai        = _openai_client()
        chroma     = _chroma_client()
        collection = chroma.get_collection(_yearly_collection_name(year))

        query_vec = embed_text(query_text, oai)
        total     = collection.count()

        # Fetch 4× to leave room for (a) temporal re-ranking swaps and
        # (b) dedup of multiple chunks from the same project.
        fetch_n = min(n_results * 4, total)
        if fetch_n <= 0:
            return []

        results = collection.query(
            query_embeddings=[query_vec],
            n_results=fetch_n,
            include=["metadatas", "distances"],
        )

        # Load full project objects for enrichment
        data_path = _yearly_projects_path(year)
        with open(data_path, encoding="utf-8") as f:
            projects_by_id = {str(p["id"]): p for p in json.load(f)}

        # Score each chunk hit with cosine + temporal, prepare for dedup
        chunk_hits = []
        for i, chunk_id in enumerate(results["ids"][0]):
            meta   = results["metadatas"][0][i] or {}
            pid    = meta.get("project_id") or _strip_chunk_id(chunk_id)
            cosine = 1.0 - results["distances"][0][i]
            temp   = _temporal_score(meta.get("year"))
            final  = SEMANTIC_WEIGHT * cosine + TEMPORAL_WEIGHT * temp
            chunk_hits.append({
                "project_id":       pid,
                "chunk_type":       meta.get("chunk_type", "unknown"),
                "similarity_score": round(final, 3),
                "cosine_score":     round(cosine, 3),
                "temporal_score":   round(temp, 3),
                "year":             meta.get("year", ""),
            })

        # Keep the best chunk per project
        best_per_project = _deduplicate_by_project(chunk_hits)

        similar = []
        for hit in best_per_project[:n_results]:
            pid  = hit["project_id"]
            proj = dict(projects_by_id.get(pid, {}))
            if not proj:
                # Paranoid fallback: search by suffix match
                for k, v in projects_by_id.items():
                    if k.startswith(pid[:20]):
                        proj = dict(v); break
            proj["similarity_score"] = hit["similarity_score"]
            proj["cosine_score"]     = hit["cosine_score"]
            proj["temporal_score"]   = hit["temporal_score"]
            proj["matched_chunk"]    = hit["chunk_type"]
            similar.append(proj)

        return similar

    except Exception as e:
        print(f"[RAG] Yearly retrieval error: {e}")
        import traceback; traceback.print_exc()
        return []


def _strip_chunk_id(chunk_id: str) -> str:
    """
    Recover the project id from a chunk id like '{project}_{idx}_{chunk_type}'.
    Falls back to full id if the pattern doesn't match.
    """
    parts = chunk_id.rsplit("_", 2)
    if len(parts) == 3 and parts[-1] in (CHUNK_SUMMARY, CHUNK_PARAMS, CHUNK_BOM):
        return parts[0]
    return chunk_id


def get_available_yearly_indices() -> list[str]:
    """Return list of years that have a built yearly index."""
    try:
        chroma = _chroma_client()
        colls  = chroma.list_collections()
        return [
            c.name.replace(YEARLY_COLLECTION_PREFIX, "")
            for c in colls
            if c.name.startswith(YEARLY_COLLECTION_PREFIX)
        ]
    except Exception:
        return []


# ── CLI helper (run directly to (re)build the index) ──────────────────────────

if __name__ == "__main__":
    import sys
    # Load .env if present
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode in ("all", "quotes"):
        build_index(force=True)
        print("\n[RAG] Test retrieval (quotes):")
        results = retrieve_similar("armoire commande 2 pompes relevage eaux usées 7.5kW IP65", n_results=3)
        for r in results:
            print(f"  [{r['similarity_score']:.3f}] {r['product_type']} – {r['summary']}")

    if mode in ("all", "yearly"):
        build_yearly_index(year="2022", force=True)
        print("\n[RAG] Test retrieval (yearly projects):")
        results = retrieve_similar_projects("armoire commande 2 pompes relevage eaux usées 7.5kW IP65", year="2022", n_results=3)
        for r in results:
            print(f"  [{r['similarity_score']:.3f}] {r['product_type']} – {r.get('description', '')} (client: {r.get('client', '')})")
