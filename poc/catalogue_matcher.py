"""
catalogue_matcher.py – Match LLM-generated BoM items against CETIE's real catalogue
=====================================================================================

After the LLM generates bom_categories with free-form component names, this module
finds the closest real catalogue item from blocks.json / armoires.json for each one.

Matching strategy (no external deps beyond stdlib):
  1. Tokenise both strings → lowercase words + extracted numbers
  2. Jaccard similarity on word tokens
  3. Numeric bonus  – numbers in LLM item that also appear in catalogue item
  4. Category pre-filter – only search blocks plausibly in the right BoM section
  5. Decision threshold:
       score >= 0.55 → VERIFIED   (replace unit_price with real catalogue price)
       score >= 0.30 → SUGGESTED  (flag as partial match, keep LLM price)
       score <  0.30 → NOT_FOUND  (flag as unverified, keep as-is)
"""

import re
import json
import os
from pathlib import Path
from typing import Optional

BASE_DIR  = Path(__file__).parent
DATA_DIR  = BASE_DIR / "data"

# ── Thresholds ────────────────────────────────────────────────────────────────
VERIFIED_THRESHOLD  = 0.55
SUGGESTED_THRESHOLD = 0.30

# ── BOM category → catalogue keyword hints ────────────────────────────────────
# Used to pre-filter the 2 661-item catalogue before scoring, for speed + accuracy.
CAT_HINTS = {
    "01_cabinet_enclosure": {
        "use_armoires": True,
        "keywords": {"coffret", "armoire", "polyester", "acier", "aluminium",
                     "enveloppe", "plm", "grolleau", "seiffel", "legrand",
                     "kit", "assemblage", "socle", "serrure"},
    },
    "02_equipment_on_side": {
        "keywords": {"interrupteur", "différentiel", "disjoncteur", "prise",
                     "service", "côté", "latéral", "porte", "intérieure"},
    },
    "04_internal_chassis_power": {
        "keywords": {"interrupteur", "général", "répartiteur", "parafoudre",
                     "sectionneur", "fusible", "jeu", "barres", "départ",
                     "disjoncteur", "contacteur", "moteur", "câblage"},
    },
    "04_internal_chassis_control": {
        "keywords": {"relais", "temporisateur", "transformateur", "alimentation",
                     "24v", "230v", "bornier", "commande", "contrôle",
                     "module", "fin", "course"},
    },
    "04_internal_chassis_automation": {
        "keywords": {"automate", "variateur", "atv", "m221", "m340", "wago",
                     "plc", "cpu", "carte", "communication", "modbus",
                     "ethernet", "gsm", "sofrel", "millenium", "millénium",
                     "schneider", "siemens", "s7", "télégestion"},
    },
    "05_equipment_on_top": {
        "keywords": {"toiture", "toit", "ventilateur", "filtre", "aération",
                     "grille", "thermostat", "climatiseur"},
    },
    "06_door_controls": {
        "keywords": {"bouton", "poussoir", "voyant", "sélecteur", "ampèremètre",
                     "voltmètre", "afficheur", "façade", "commande", "boutonnerie",
                     "lumineux", "heure", "compteur", "porte"},
    },
    "07_supplied_separately": {
        "keywords": {"sonde", "capteur", "niveau", "flotteur", "pressostrat",
                     "fourni", "séparé", "client"},
    },
    "09_commissioning": {
        "keywords": {"mise", "service", "essai", "déplacement", "transport",
                     "paramétrage", "programmation"},
    },
    "10_packaging": {
        "keywords": {"emballage", "caisse", "palette", "transport", "livraison"},
    },
    "11_labor": {
        "keywords": {"main", "oeuvre", "œuvre", "câblage", "montage",
                     "programmation", "heure", "forfait"},
    },
    "12_options": {
        "keywords": {"option", "variante", "accessoire", "supplément"},
    },
}

# ── Tokeniser ─────────────────────────────────────────────────────────────────
_STOPWORDS = {
    "de", "du", "des", "le", "la", "les", "un", "une", "et", "en",
    "à", "au", "aux", "par", "pour", "sur", "avec", "sans", "ou",
    "sa", "son", "ses", "ce", "cet", "cette", "ces",
    "d", "l", "j", "m", "s",   # elided articles
}

def _tokenise(text: str) -> tuple:
    """Return (word_tokens: set, number_tokens: set)."""
    text = text.lower()
    # Split on non-alphanumeric (keep digits separate)
    raw   = re.split(r"[^a-zàâçéèêëîïôùûü0-9]+", text)
    words  = set()
    numbers = set()
    for tok in raw:
        if not tok:
            continue
        if re.fullmatch(r"\d+[\.,]?\d*", tok):
            numbers.add(tok.replace(",", "."))
        elif tok not in _STOPWORDS and len(tok) > 1:
            words.add(tok)
    return words, numbers


def _score(llm_words, llm_nums, cat_words, cat_nums) -> float:
    """Weighted similarity: Jaccard on words + numeric overlap bonus."""
    union = llm_words | cat_words
    if not union:
        return 0.0
    jaccard = len(llm_words & cat_words) / len(union)

    # Numeric bonus: reward exact number matches (amps, dimensions, etc.)
    num_bonus = 0.0
    if llm_nums and cat_nums:
        matched_nums = llm_nums & cat_nums
        num_bonus = 0.25 * (len(matched_nums) / len(llm_nums))

    return min(1.0, jaccard + num_bonus)


# ── Catalogue index (built once at import time) ───────────────────────────────

class _CatalogueIndex:
    def __init__(self):
        self.blocks   = []   # all items from blocks.json + armoires.json
        self._indexed = []   # list of (words, nums, block_dict)
        self._ready   = False

    def build(self):
        blocks_path   = DATA_DIR / "blocks.json"
        armoires_path = DATA_DIR / "armoires.json"

        items = []
        if blocks_path.exists():
            with open(blocks_path, encoding="utf-8") as f:
                items += [dict(b, _source="blocks") for b in json.load(f)]
        if armoires_path.exists():
            with open(armoires_path, encoding="utf-8") as f:
                items += [dict(a, _source="armoires") for a in json.load(f)]

        self.blocks = items
        self._indexed = []
        for b in items:
            w, n = _tokenise(b.get("designation", "") + " " + b.get("categorie", ""))
            self._indexed.append((w, n, b))

        self._ready = True
        print(f"[CatalogueIndex] Built index: {len(self.blocks)} items")

    def search(self, designation: str, bom_category: str,
               top_k: int = 3) -> list:
        """Return top_k matches as list of {block, score, status}."""
        if not self._ready:
            self.build()

        hints    = CAT_HINTS.get(bom_category, {})
        hint_kws = hints.get("keywords", set())
        use_arm  = hints.get("use_armoires", False)

        llm_words, llm_nums = _tokenise(designation)
        if not llm_words and not llm_nums:
            return []

        scored = []
        for (cat_words, cat_nums, block) in self._indexed:
            # Skip armoire items unless this is an enclosure category
            if block["_source"] == "armoires" and not use_arm:
                continue
            # Skip blocks with zero price (template stubs)
            if block.get("cout", 0) == 0:
                continue
            # Pre-filter by category hints (must share ≥1 hint keyword)
            if hint_kws:
                block_text = (
                    block.get("designation", "") + " " +
                    block.get("categorie", "") + " " +
                    block.get("label", "")
                ).lower()
                if not any(kw in block_text for kw in hint_kws):
                    continue

            s = _score(llm_words, llm_nums, cat_words, cat_nums)
            if s > 0:
                scored.append((s, block))

        scored.sort(key=lambda x: -x[0])
        top = scored[:top_k]

        results = []
        for score, block in top:
            if score >= VERIFIED_THRESHOLD:
                status = "verified"
            elif score >= SUGGESTED_THRESHOLD:
                status = "suggested"
            else:
                status = "not_found"
            results.append({
                "score":       round(score, 3),
                "status":      status,
                "catalogue_id":      block.get("id"),
                "catalogue_designation": block.get("designation", ""),
                "catalogue_category":    block.get("categorie", ""),
                "unit_price":  block.get("cout", 0),
                "hours":       block.get("heures_cablage", 0),
            })

        return results


# Singleton index — built once per process
_INDEX = _CatalogueIndex()


def get_index() -> _CatalogueIndex:
    if not _INDEX._ready:
        _INDEX.build()
    return _INDEX


# ── Public API ────────────────────────────────────────────────────────────────

def match_item(designation: str, bom_category: str) -> dict:
    """
    Find the best catalogue match for a single LLM-generated item.

    Returns a dict with keys:
      llm_designation   – original LLM text
      status            – 'verified' | 'suggested' | 'not_found'
      catalogue_id      – int or None
      catalogue_designation – str
      unit_price        – real catalogue price (or 0 if not found)
      hours             – real wiring hours (or 0)
      match_score       – float 0-1
      top_matches       – list of top-3 candidates (for debug)
    """
    idx     = get_index()
    matches = idx.search(designation, bom_category, top_k=3)

    if not matches or matches[0]["status"] == "not_found":
        return {
            "llm_designation":       designation,
            "status":                "not_found",
            "catalogue_id":          None,
            "catalogue_designation": None,
            "unit_price":            0,
            "hours":                 0,
            "match_score":           matches[0]["score"] if matches else 0,
            "top_matches":           matches,
        }

    best = matches[0]
    return {
        "llm_designation":       designation,
        "status":                best["status"],
        "catalogue_id":          best["catalogue_id"],
        "catalogue_designation": best["catalogue_designation"],
        "unit_price":            best["unit_price"],
        "hours":                 best["hours"],
        "match_score":           best["score"],
        "top_matches":           matches,
    }


def match_bom_categories(bom_categories: dict) -> dict:
    """
    Process all items in a bom_categories dict.
    Enriches each item with catalogue match info.
    Returns the same structure with extra fields added to each item.

    Extra fields added per item:
      match_status      – 'verified' | 'suggested' | 'not_found'
      match_score       – float
      catalogue_id      – int or None
      catalogue_designation – str or None
      unit_price        – real price if verified/suggested, else 0
      hours             – real wiring hours if verified/suggested, else 0
    """
    result = {}
    stats  = {"verified": 0, "suggested": 0, "not_found": 0, "skipped": 0}

    for cat_key, items in bom_categories.items():
        if not isinstance(items, list):
            result[cat_key] = items
            continue

        enriched = []
        for item in items:
            desig = item.get("designation", "")

            # Skip labor / text items — no catalogue match needed
            if cat_key == "11_labor" or not desig or desig.startswith("Main d"):
                enriched.append({**item, "match_status": "skipped",
                                  "match_score": 1.0, "catalogue_id": None})
                stats["skipped"] += 1
                continue

            m = match_item(desig, cat_key)
            enriched_item = {
                **item,
                "match_status":           m["status"],
                "match_score":            m["match_score"],
                "catalogue_id":           m["catalogue_id"],
                "catalogue_designation":  m["catalogue_designation"],
            }

            # If verified or suggested, use real catalogue price + hours
            if m["status"] in ("verified", "suggested") and m["unit_price"] > 0:
                enriched_item["unit_price"] = m["unit_price"]
                enriched_item["hours"]      = m["hours"]

            stats[m["status"]] += 1
            enriched.append(enriched_item)

        result[cat_key] = enriched

    result["_match_stats"] = stats
    return result


def match_summary(bom_categories: dict) -> str:
    """Human-readable one-liner summary of match quality."""
    stats = bom_categories.get("_match_stats", {})
    if not stats:
        return "no match stats"
    v = stats.get("verified", 0)
    s = stats.get("suggested", 0)
    n = stats.get("not_found", 0)
    total = v + s + n
    if total == 0:
        return "no items to match"
    return (f"{v}/{total} verified ({v/total:.0%})  "
            f"{s} suggested  {n} not found")


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    idx = get_index()
    print()

    test_cases = [
        ("Coffret polyester double porte 847x636x300 IP65",        "01_cabinet_enclosure"),
        ("Interrupteur général 3x63A avec poignée de commande frontale", "04_internal_chassis_power"),
        ("Répartiteur tétrapolaire 125A 11 connecteurs",           "04_internal_chassis_power"),
        ("Parafoudre général TRI+N avec protection",               "04_internal_chassis_power"),
        ("Départ disjoncteur contacteur moteur 6-10A par pompe",   "04_internal_chassis_power"),
        ("Variateur ATV320 7.5kW 400V",                            "04_internal_chassis_automation"),
        ("Automate Millénium III",                                  "04_internal_chassis_automation"),
        ("Bouton poussoir lumineux vert démarrage",                 "06_door_controls"),
        ("Voyant lumineux rouge défaut",                            "06_door_controls"),
        ("Main d'œuvre câblage",                                    "11_labor"),
        ("Antenne GSM 4G pour télégestion",                        "04_internal_chassis_automation"),
        ("Composant totalement inventé XYZ-9999",                   "04_internal_chassis_power"),
    ]

    for desig, cat in test_cases:
        m = match_item(desig, cat)
        icon = {"verified": "✅", "suggested": "⚠️", "not_found": "❌"}[m["status"]]
        print(f"{icon} [{m['status']:9}] score={m['match_score']:.2f}  "
              f"LLM: {desig[:45]:<45} → CAT: {(m['catalogue_designation'] or 'no match')[:45]}"
              f"  €{m['unit_price']:.2f}")
