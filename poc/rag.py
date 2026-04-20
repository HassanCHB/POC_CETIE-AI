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
import json
import glob
import chromadb
from openai import OpenAI

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(__file__)
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")
QUOTES_PATH = os.path.join(BASE_DIR, "data", "historical_quotes.json")
COLLECTION  = "historical_quotes"
YEARLY_COLLECTION_PREFIX = "yearly_projects_"

# ── Helpers ────────────────────────────────────────────────────────────────────

def _openai_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in environment / .env")
    return OpenAI(api_key=api_key)


def _chroma_client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=CHROMA_PATH)


def embed_text(text: str, client=None) -> list[float]:
    """Embed a single string with text-embedding-3-small."""
    if client is None:
        client = _openai_client()
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text.replace("\n", " "),
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
    Convert a yearly DEVIS project into a rich embeddable string.

    Three layers of similarity are embedded:
      1. Application context  — what the client asked for
      2. Technical architecture — component structure by category (key improvement)
      3. Quantitative profile  — hours, I/O counts, motor count, tags
    """
    parts = []

    # ── Layer 1: Application context ──────────────────────────────────────────
    parts.append(project.get("client_request", ""))
    parts.append(project.get("description", ""))
    parts.append(project.get("divalto_designation", ""))
    parts.append(project.get("product_type", ""))
    parts.append(project.get("metier", ""))

    # ── Layer 2: Technical architecture ───────────────────────────────────────
    # architecture_text captures category-level component structure + tech keywords
    arch = project.get("architecture_text", "")
    if arch:
        parts.append(arch)
    else:
        # Fallback for data parsed before this improvement
        cfg = project.get("configuration", {})
        parts.append(" ".join(cfg.get("key_components", [])[:8]))

    # ── Layer 3: Quantitative technical profile ────────────────────────────────
    if project.get("nb_motors"):
        parts.append(f"{project['nb_motors']} moteurs")

    cfg    = project.get("configuration", {})
    h_fab  = cfg.get("hours_fabrication", 0) or 0
    h_prog = cfg.get("hours_programmation", 0) or 0
    if h_fab:  parts.append(f"câblage {h_fab}h")
    if h_prog: parts.append(f"automatisme {h_prog}h")

    # I/O profile — indicates automation complexity
    io = project.get("io", {})
    if io.get("total", 0) > 0:
        parts.append(
            f"{io.get('digital_in', 0)}DI {io.get('digital_out', 0)}DO "
            f"{io.get('analog_in', 0)}AI {io.get('analog_out', 0)}AO"
        )

    # Tags: brands, protocols, IP ratings, application type
    parts.append(" ".join(project.get("tags", [])))

    return " ".join(p for p in parts if p).strip()


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

        results = collection.query(
            query_embeddings=[query_vec],
            n_results=min(n_results, collection.count()),
            include=["metadatas", "distances"],
        )

        # Load full quote objects
        with open(QUOTES_PATH, encoding="utf-8") as f:
            quotes_by_id = {str(q["id"]): q for q in json.load(f)}

        similar = []
        for i, qid in enumerate(results["ids"][0]):
            quote = dict(quotes_by_id.get(qid, {}))
            # cosine distance → similarity score (1 = identical)
            quote["similarity_score"] = round(1.0 - results["distances"][0][i], 3)
            similar.append(quote)

        return similar

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

    ids, embeddings, documents, metadatas = [], [], [], []

    for idx, p in enumerate(projects):
        text = _project_to_text(p)
        if not text.strip():
            continue
        vec = embed_text(text, oai)

        conf = p.get("configuration", {})
        # Use idx-prefixed ID to guarantee uniqueness even if devis numbers repeat
        unique_id = f"{p['id']}_{idx}"
        ids.append(unique_id)
        embeddings.append(vec)
        documents.append(text)
        def _s(v, default=""):
            """Convert any value to a safe string for ChromaDB metadata."""
            return str(v) if v is not None else default

        io = p.get("io", {})
        metadatas.append({
            "id":               _s(p.get("id", idx)),
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
            "tags":             " ".join(p.get("tags", []))[:200],
        })

    if ids:
        collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
        print(f"[RAG] Yearly index built — {len(ids)} projects embedded.")
    else:
        print("[RAG] No projects to embed.")


def retrieve_similar_projects(query_text: str, year: str = "2022", n_results: int = 5) -> list[dict]:
    """
    Find the N most similar yearly DEVIS projects to query_text.
    Returns list of project dicts enriched with similarity_score.
    Falls back to [] if the index is not ready.
    """
    if not is_yearly_index_ready(year):
        print(f"[RAG] Yearly index for {year} not ready — skipping.")
        return []

    try:
        oai        = _openai_client()
        chroma     = _chroma_client()
        collection = chroma.get_collection(_yearly_collection_name(year))

        query_vec = embed_text(query_text, oai)

        results = collection.query(
            query_embeddings=[query_vec],
            n_results=min(n_results, collection.count()),
            include=["metadatas", "distances"],
        )

        # Load full project objects
        data_path = _yearly_projects_path(year)
        with open(data_path, encoding="utf-8") as f:
            projects_by_id = {str(p["id"]): p for p in json.load(f)}

        similar = []
        for i, unique_pid in enumerate(results["ids"][0]):
            # Strip the _idx suffix added during indexing
            pid = "_".join(unique_pid.split("_")[:-1]) if "_" in unique_pid else unique_pid
            proj = dict(projects_by_id.get(pid, {}))
            if not proj:
                # Fallback: try the full id
                proj = dict(projects_by_id.get(unique_pid, {}))
            proj["similarity_score"] = round(1.0 - results["distances"][0][i], 3)
            similar.append(proj)

        return similar

    except Exception as e:
        print(f"[RAG] Yearly retrieval error: {e}")
        return []


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
