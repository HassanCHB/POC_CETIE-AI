"""
test_pipeline_suite.py — End-to-end pipeline test suite
========================================================

Runs a diverse set of customer requests through the full pipeline (extraction →
retrieval → accessories-rules matching → LLM configuration) and checks the
output against expected behaviours. Acts as both a regression gate and a demo
suite that exercises every rule + retrieval path.

Each test case defines:
  • The customer request (as a tester would type it)
  • The accessory rules we expect to trigger
  • Keywords we expect to find in the generated BoM

Usage
-----
    python3 poc/test_pipeline_suite.py                 # run all tests
    python3 poc/test_pipeline_suite.py --case 3        # just case #3
    python3 poc/test_pipeline_suite.py --dump out.json # save full outputs
    python3 poc/test_pipeline_suite.py --quick         # skip LLM generation,
                                                       # only test extraction + retrieval
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

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


# ══════════════════════════════════════════════════════════════════════════
# Test cases
# ══════════════════════════════════════════════════════════════════════════

TESTS = [
    {
        "id": 1,
        "name": "T1 — Simple monophase coffret",
        "request": "Coffret simple pour 1 pompe domestique 0.55 kW mono 230VAC, IP55, bouton marche/arrêt + voyant présence tension.",
        "expected_rules": ["IP65 / IP66"],  # IP55 doesn't match the rule exactly but ok
        "must_have": ["coffret", "voyant"],
        "must_have_cat": ["01_cabinet_enclosure", "04_internal_chassis_power", "06_door_controls"],
        "max_items": 20,
        "complexity": "simple",
    },
    {
        "id": 2,
        "name": "T2 — Feedback Test 1 (déporté + S4W + double enveloppe)",
        "request": "Armoire double enveloppe extérieur 2 pompes 1.7kW Sofrel S4W sonde Piézo + débitmètre Promag déporté",
        "expected_rules": ["Installation extérieure", "Double enveloppe", "Équipement déporté",
                           "Sonde Piézo", "Débitmètre électromagnétique", "Télégestion Sofrel S4W"],
        "must_have": ["socle", "déporté", "s4w", "sonde", "ventilation"],
        "must_have_cat": ["01_cabinet_enclosure", "04_internal_chassis_automation",
                          "07_supplied_separately", "06_door_controls"],
        "complexity": "complex",
    },
    {
        "id": 3,
        "name": "T3 — Feedback Test 2 (horloge + socle extérieur)",
        "request": "Armoire 1 pompe 5.5kW commande par horloge hebdomadaire extérieur sur socle",
        "expected_rules": ["Installation extérieure", "Horloge hebdomadaire"],
        "must_have": ["socle", "horloge"],
        "must_have_cat": ["01_cabinet_enclosure", "04_internal_chassis_control", "06_door_controls"],
        "complexity": "medium",
    },
    {
        "id": 4,
        "name": "T4 — 3-pump VFD + PLC (ATV630 + S7-1200)",
        "request": "Armoire de surpression 3 pompes 22kW 44A chacune avec variateur ATV630, automate Siemens S7-1200, Profinet, capteur pression 4-20mA, IP54",
        "expected_rules": ["Variateur Schneider Altivar", "Automate Siemens S7-1200"],
        "must_have": ["atv", "s7-1200", "filtre", "ventilation"],
        "must_have_cat": ["01_cabinet_enclosure", "04_internal_chassis_power",
                          "04_internal_chassis_automation", "06_door_controls"],
        "complexity": "complex",
    },
    {
        "id": 5,
        "name": "T5 — Soft starter + alternance",
        "request": "Armoire 2 pompes 15kW 30A avec démarreurs progressifs ATS01 et alternance automatique pompes, station de relevage eaux usées",
        "expected_rules": ["Démarreur progressif ATS", "Alternance de pompes"],
        "must_have": ["démarreur", "alternance", "compteur horaire"],
        "must_have_cat": ["01_cabinet_enclosure", "04_internal_chassis_power",
                          "04_internal_chassis_control", "06_door_controls_power"],
        "complexity": "medium",
    },
    {
        "id": 6,
        "name": "T6 — Inverseur de source + groupe électrogène",
        "request": "Armoire 2 pompes 11kW station de pompage avec inverseur de source automatique EDF/groupe électrogène, Millénium III, arrêt d'urgence",
        "expected_rules": ["Inverseur de sources / double alimentation",
                           "Relais programmable (Millénium / Zélio / LOGO!)",
                           "Arrêt d'urgence"],
        "must_have": ["inverseur", "millenium", "arrêt"],
        "must_have_cat": ["01_cabinet_enclosure", "04_internal_chassis_power",
                          "04_internal_chassis_automation", "06_door_controls"],
        "complexity": "complex",
    },
    {
        "id": 7,
        "name": "T7 — Poires de niveau + gyrophare défaut",
        "request": "Armoire 2 pompes eaux usées 2.4kW avec poires de niveau, gyrophare défaut sur toit armoire, alternance, IP65",
        "expected_rules": ["Alternance de pompes", "Alarme sonore / gyrophare",
                           "Poires de niveau", "IP65 / IP66"],
        "must_have": ["poire", "gyrophare", "alternance"],
        "must_have_cat": ["01_cabinet_enclosure", "04_internal_chassis_control",
                          "05_equipment_on_top", "06_door_controls"],
        "complexity": "medium",
    },
    {
        "id": 8,
        "name": "T8 — Modem alerte SMS + mise en service",
        "request": "Armoire 1 pompe 7.5kW 15A avec modem alerte SMS, voyants défaut, mise en service sur site département 49",
        "expected_rules": ["Modem alerte SMS / GSM", "Mise en service sur site / FAT"],
        "must_have": ["modem", "antenne", "mise en service"],
        "must_have_cat": ["01_cabinet_enclosure", "04_internal_chassis_automation",
                          "09_commissioning"],
        "complexity": "medium",
    },
    {
        "id": 9,
        "name": "T9 — Sonde ultrason Datalogger",
        "request": "Armoire 2 pompes 3kW avec Datalogger LT-US DL4W-HP et sonde ultrason pour mesure hauteur",
        "expected_rules": ["Sonde ultrason", "Télégestion Sofrel S4W"],
        "must_have": ["sonde", "ultrason", "4-20"],
        "must_have_cat": ["04_internal_chassis_automation", "01_cabinet_enclosure"],
        "complexity": "medium",
    },
    {
        "id": 10,
        "name": "T10 — Large outdoor: 4 pumps, multiple features",
        "request": "Armoire station de relevage extérieur sur socle 4 pompes 18.5kW démarreurs ATS490, Sofrel S4W, sonde Piézo, arrêt d'urgence, gyrophare, double enveloppe, IP66",
        "expected_rules": ["Installation extérieure", "Double enveloppe", "Démarreur progressif ATS",
                           "Télégestion Sofrel S4W", "Sonde Piézo", "Arrêt d'urgence",
                           "Alarme sonore / gyrophare", "IP65 / IP66"],
        "must_have": ["socle", "démarreur", "s4w", "sonde", "gyrophare", "arrêt"],
        "must_have_cat": ["01_cabinet_enclosure", "04_internal_chassis_power",
                          "04_internal_chassis_automation", "05_equipment_on_top",
                          "06_door_controls", "06_door_controls_power"],
        "complexity": "complex",
    },
]


# ══════════════════════════════════════════════════════════════════════════
# Pipeline execution
# ══════════════════════════════════════════════════════════════════════════

def extract_requirements(request: str) -> dict:
    prompt = f"""You are an expert at CETIE. Extract key technical requirements from this customer request:

<request>
{request}
</request>

Respond ONLY with JSON:
{{"product_type":"brief type","power_kw":null_or_number,"nb_motors":null_or_number,
"voltage":null_or_string,"ip_rating":null_or_string,"automation":null_or_string,
"sector":null_or_string,"keywords":["..."],"summary":"1 sentence"}}"""
    msg = client.messages.create(model="claude-sonnet-4-6", max_tokens=500,
                                  messages=[{"role": "user", "content": prompt}])
    try:
        from json_repair import repair_json
        return json.loads(repair_json(msg.content[0].text))
    except Exception:
        return {"keywords": [], "summary": request[:100]}


def retrieve_projects(request: str, per_year: int = 3) -> list:
    out = []
    for year in ["2022", "2026"]:
        try:
            for h in rag.retrieve_similar_projects(request, year=year, n_results=per_year):
                h["_year"] = year
                out.append(h)
        except Exception:
            pass
    out.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)
    return out[:5]


def build_yearly_section(projects: list) -> str:
    if not projects:
        return ""
    parts = []
    for i, p in enumerate(projects[:3]):
        conf = p.get("configuration", {})
        cats = conf.get("by_category", {})
        bom_lines = []
        for cat, items in cats.items():
            if items:
                bom_lines.append(f"  [{cat}]:")
                for it in items[:15]:
                    q = it.get("quantity", 1)
                    d = it.get("designation", "")
                    up = it.get("unit_price", 0) or 0
                    bom_lines.append(f"    - {q}x {d} @ {up:.2f}€")
        parts.append(
            f"--- Real DEVIS #{i+1} [{p.get('_year','')}] ref={p.get('id','')[:30]} (sim: {p['similarity_score']:.0%}) ---\n"
            f"Client: {p.get('client','')} | Description: {p.get('description','')}\n"
            f"Fabrication: {conf.get('hours_fabrication',0)}h | Prog: {conf.get('hours_programmation',0)}h | "
            f"Matière: {conf.get('cost_material',0):.0f}€ | Prix devis: {conf.get('base_price',0):.0f}€\n"
            f"BoM (use these exact designations):\n" + "\n".join(bom_lines)
        )
    return "\n=== Real CETIE DEVIS projects — primary reference ===\n" + "\n\n".join(parts) + "\n"


def generate_config(request: str, requirements: dict, yearly: str, accessories: str) -> dict:
    prompt = f"""You are a CETIE technical expert configuring electrical control panels.

Customer request: {request}

Extracted requirements:
{json.dumps(requirements, ensure_ascii=False)}
{yearly}{accessories}
GROUNDING: designations must come from the retrieved DEVIS or catalogue. Every item must have a "source" field ("devis:<ref>" or "catalogue").

Respond ONLY with JSON:
{{
  "bom_categories": {{
    "01_cabinet_enclosure":[], "02_equipment_on_side":[], "04_internal_chassis_power":[],
    "04_internal_chassis_control":[], "04_internal_chassis_automation":[],
    "05_equipment_on_top":[], "06_door_controls":[], "06_door_controls_power":[],
    "07_supplied_separately":[], "09_commissioning":[], "10_packaging":[],
    "11_labor":[{{"designation":"Main d'œuvre câblage","quantity":1,"hours":0}},{{"designation":"Main d'œuvre programmation","quantity":1,"hours":0}}],
    "12_options":[]
  }},
  "total_hours_cablage":number,"total_hours_prog":number,
  "estimated_material_cost":number,"estimated_price":number,
  "assumptions":["..."],"missing_info":["..."],"expert_notes":"..."
}}

Each item in bom_categories: {{"designation":"exact","quantity":N,"unit_price":€,"source":"devis:... or catalogue"}}"""
    msg = client.messages.create(model="claude-opus-4-7", max_tokens=6000,
                                  messages=[{"role": "user", "content": prompt}])
    try:
        from json_repair import repair_json
        return json.loads(repair_json(msg.content[0].text))
    except Exception as e:
        return {"error": str(e), "raw": msg.content[0].text[:500]}


def run_one(test: dict, quick: bool = False) -> dict:
    t0 = time.time()
    req = test["request"]

    # Requirements
    reqs = extract_requirements(req)

    # Retrieval
    projects = retrieve_projects(req)

    # Accessory rules
    acc_section = app.get_applicable_accessories(req)
    acc_labels = re.findall(r"▪ ([^(]+?)\s+\(", acc_section)
    acc_labels = [l.strip() for l in acc_labels]

    result = {
        "id": test["id"],
        "name": test["name"],
        "request": req,
        "requirements": reqs,
        "retrieved": [{"id": p.get("id"), "client": p.get("client"),
                       "sim": p.get("similarity_score")} for p in projects],
        "acc_labels": acc_labels,
        "elapsed_s": 0,
    }

    if quick:
        result["elapsed_s"] = round(time.time() - t0, 1)
        return result

    # Config generation
    yearly = build_yearly_section(projects)
    cfg = generate_config(req, reqs, yearly, acc_section)
    result["configuration"] = cfg
    result["elapsed_s"] = round(time.time() - t0, 1)
    return result


# ══════════════════════════════════════════════════════════════════════════
# Validation
# ══════════════════════════════════════════════════════════════════════════

def validate(result: dict, test: dict, quick: bool = False) -> dict:
    checks = []

    # 1) Expected accessory rules all triggered
    expected = set(test["expected_rules"])
    got = set(result["acc_labels"])
    missing_rules = expected - got
    checks.append({
        "name": "Accessory rules triggered",
        "pass": not missing_rules,
        "detail": f"matched {len(got & expected)}/{len(expected)}" + (
            f", missing: {sorted(missing_rules)}" if missing_rules else ""),
    })

    # 2) At least 1 retrieval hit
    checks.append({
        "name": "Retrieval returned projects",
        "pass": len(result["retrieved"]) > 0,
        "detail": f"{len(result['retrieved'])} hits",
    })

    # 3) Top-1 similarity reasonable
    top_sim = result["retrieved"][0]["sim"] if result["retrieved"] else 0
    checks.append({
        "name": "Top-1 similarity ≥ 0.55",
        "pass": top_sim >= 0.55,
        "detail": f"top_sim = {top_sim:.3f}",
    })

    if quick:
        return {"checks": checks, "passed": sum(1 for c in checks if c["pass"]),
                "total": len(checks)}

    cfg = result.get("configuration", {})
    if "error" in cfg:
        checks.append({"name": "Config generation succeeded", "pass": False,
                       "detail": f"ERROR: {cfg['error']}"})
        return {"checks": checks, "passed": sum(1 for c in checks if c["pass"]),
                "total": len(checks)}

    # 4) Config JSON parsed
    checks.append({"name": "Config generation succeeded", "pass": True, "detail": "parsed OK"})

    bom = cfg.get("bom_categories", {})
    bom_flat_text = json.dumps(bom, ensure_ascii=False).lower()

    # 5) Required categories populated
    missing_cats = [c for c in test["must_have_cat"]
                    if not (isinstance(bom.get(c), list) and bom.get(c))]
    checks.append({
        "name": "Required BoM categories populated",
        "pass": not missing_cats,
        "detail": f"missing: {missing_cats}" if missing_cats else "all present",
    })

    # 6) Required keywords present in BoM text
    missing_kw = [kw for kw in test["must_have"] if kw.lower() not in bom_flat_text]
    checks.append({
        "name": "Required keywords present in BoM",
        "pass": not missing_kw,
        "detail": f"missing: {missing_kw}" if missing_kw else "all present",
    })

    # 7) Every item has a source field
    missing_source = 0
    total_items = 0
    for items in bom.values():
        if isinstance(items, list):
            for it in items:
                total_items += 1
                if not it.get("source"):
                    missing_source += 1
    checks.append({
        "name": "All items have source citation",
        "pass": missing_source == 0,
        "detail": f"{total_items - missing_source}/{total_items} sourced"
                  + (f" ({missing_source} missing)" if missing_source else ""),
    })

    # 8) Hours / price are non-zero and in sensible ranges
    fab = cfg.get("total_hours_cablage", 0) or 0
    prog = cfg.get("total_hours_prog", 0) or 0
    price = cfg.get("estimated_price", 0) or 0
    # ranges depend on complexity
    bounds = {
        "simple":  {"fab": (1, 15), "price": (300, 3000)},
        "medium":  {"fab": (5, 40), "price": (1000, 8000)},
        "complex": {"fab": (15, 80), "price": (3000, 30000)},
    }[test.get("complexity", "medium")]
    fab_ok = bounds["fab"][0] <= fab <= bounds["fab"][1]
    price_ok = bounds["price"][0] <= price <= bounds["price"][1]
    checks.append({
        "name": f"Hours in plausible range ({bounds['fab'][0]}-{bounds['fab'][1]}h)",
        "pass": fab_ok, "detail": f"{fab}h fab, {prog}h prog",
    })
    checks.append({
        "name": f"Price in plausible range ({bounds['price'][0]}-{bounds['price'][1]}€)",
        "pass": price_ok, "detail": f"{price:.0f}€",
    })

    # 9) BoM density matches complexity
    if test.get("max_items"):
        checks.append({
            "name": f"BoM size ≤ {test['max_items']} items (simple case)",
            "pass": total_items <= test["max_items"],
            "detail": f"{total_items} items",
        })
    elif test.get("complexity") == "complex":
        checks.append({
            "name": "BoM has ≥ 25 items (complex case)",
            "pass": total_items >= 25,
            "detail": f"{total_items} items",
        })

    return {"checks": checks, "passed": sum(1 for c in checks if c["pass"]),
            "total": len(checks)}


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def print_test_banner(test: dict):
    print(f"\n{'═' * 78}")
    print(f" [{test['id']:>2}/{len(TESTS)}]  {test['name']}")
    print(f" {test['request'][:110]}")
    print(f"{'═' * 78}")


def print_test_result(res: dict, val: dict):
    print(f"\n▶ Requirements: {res['requirements'].get('product_type','?')} "
          f"| {res['requirements'].get('power_kw','?')}kW "
          f"| {res['requirements'].get('nb_motors','?')} motors "
          f"| automation: {res['requirements'].get('automation','?')}")

    print(f"▶ Retrieved top-3:")
    for p in res["retrieved"][:3]:
        print(f"   [{p['sim']:.3f}]  {p.get('client','?'):<22} {p.get('id','')[:50]}")

    print(f"▶ Accessory rules triggered ({len(res['acc_labels'])}):")
    for lbl in res["acc_labels"]:
        print(f"   • {lbl}")

    cfg = res.get("configuration", {})
    if cfg and "error" not in cfg:
        bom = cfg.get("bom_categories", {})
        total_items = sum(len(v) for v in bom.values() if isinstance(v, list))
        cats_filled = sum(1 for v in bom.values() if isinstance(v, list) and v)
        print(f"▶ BoM: {total_items} items across {cats_filled} categories | "
              f"{cfg.get('total_hours_cablage',0)}h câblage + "
              f"{cfg.get('total_hours_prog',0)}h prog | "
              f"€{cfg.get('estimated_price',0):.0f}")

    print(f"\n▶ Checks  ({val['passed']}/{val['total']} passed):")
    for c in val["checks"]:
        icon = "✓" if c["pass"] else "✗"
        print(f"   {icon} {c['name']:<45} {c['detail']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case",  type=int, default=None, help="Run a single test case by id")
    ap.add_argument("--quick", action="store_true", help="Skip LLM config generation")
    ap.add_argument("--dump",  type=str, default=None, help="Write full JSON output to file")
    args = ap.parse_args()

    cases = [t for t in TESTS if args.case is None or t["id"] == args.case]
    if not cases:
        print(f"No test with id {args.case}")
        sys.exit(1)

    print(f"{'=' * 78}")
    print(f" CETIE Pipeline Test Suite")
    print(f" Running {len(cases)} case(s)  |  Quick mode: {args.quick}")
    print(f" Rules loaded: {len(app.ACCESSORIES_RULES)}")
    print(f"{'=' * 78}")

    suite_start = time.time()
    all_results = []
    all_validations = []

    for test in cases:
        print_test_banner(test)
        try:
            res = run_one(test, quick=args.quick)
            val = validate(res, test, quick=args.quick)
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            import traceback; traceback.print_exc()
            res = {"id": test["id"], "name": test["name"], "error": str(e)}
            val = {"checks": [{"name": "ran without exception", "pass": False, "detail": str(e)}],
                   "passed": 0, "total": 1}

        print_test_result(res, val)
        all_results.append(res)
        all_validations.append(val)

    # ── Summary ──────────────────────────────────────────────────────────────
    total_elapsed = time.time() - suite_start
    print(f"\n\n{'═' * 78}")
    print(f" SUITE SUMMARY")
    print(f"{'═' * 78}")
    print(f" {'Test':<55}  {'Pass':>8}  {'Time':>7}")
    print(f" {'-' * 55}  {'-' * 8}  {'-' * 7}")
    total_passed = 0
    total_checks = 0
    for res, val in zip(all_results, all_validations):
        pct = val["passed"] / val["total"] if val["total"] else 0
        icon = "✓" if val["passed"] == val["total"] else (
               "⚠" if pct >= 0.8 else "✗")
        print(f" {icon} {res['name']:<53}  {val['passed']:>2}/{val['total']:<2}    "
              f"{res.get('elapsed_s', 0):>5.1f}s")
        total_passed += val["passed"]
        total_checks += val["total"]
    print(f" {'-' * 55}  {'-' * 8}  {'-' * 7}")
    print(f" {'TOTAL':<55}  {total_passed:>2}/{total_checks:<2}    {total_elapsed:>5.1f}s")
    overall_pct = total_passed / total_checks if total_checks else 0
    print(f"\n Overall pass rate: {overall_pct:.0%}  ({total_passed}/{total_checks} checks)")

    if args.dump:
        payload = {"tests": all_results, "validations": all_validations,
                   "summary": {"total_passed": total_passed, "total_checks": total_checks,
                               "pass_rate": round(overall_pct, 3),
                               "elapsed_s": round(total_elapsed, 1)}}
        Path(args.dump).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"\n Full output written to {args.dump}")

    # Exit code for CI-style use
    sys.exit(0 if overall_pct >= 0.85 else 1)


if __name__ == "__main__":
    main()
