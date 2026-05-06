#!/usr/bin/env bash
# prepare_for_deploy.sh — Pre-push verification routine
#
# Runs the full local pipeline: catalogue sync → JSON regeneration → 3-layer
# validation. Exits non-zero if anything looks off, so you can wire this into
# a git hook or CI step before pushing to GitHub → Render.
#
# Usage:
#   bash poc/prepare_for_deploy.sh           # full check
#   bash poc/prepare_for_deploy.sh --quick   # skip the slow Layer-2 embed test
#
# After this passes, git add + push via GitHub Desktop is safe.

set -e   # exit on first failure
cd "$(dirname "$0")/.."   # project root

QUICK=""
if [ "${1:-}" = "--quick" ]; then
  QUICK="--no-llm"
  echo ">>> Quick mode: skipping Layer-3 LLM retrieval test"
fi

echo "==========================================================="
echo " CETIE — pre-push verification"
echo " $(date)"
echo "==========================================================="

# ── Discover all year folders present in yearly_data/ ────────────
# This means dropping a new yearly_data/2027/ folder is enough — the
# script auto-picks it up without any code changes.
if [ ! -d yearly_data ]; then
  echo "  ⚠ yearly_data/ not found — nothing to parse. Place your DEVIS folders"
  echo "    under yearly_data/<year>/ first. See SETUP.md step 5."
  exit 1
fi

YEARS=$(find yearly_data -maxdepth 1 -mindepth 1 -type d \
        | grep -E "/[0-9]{4}$" \
        | sed 's|.*/||' | sort -u)

if [ -z "$YEARS" ]; then
  echo "  ⚠ No 4-digit year folders found in yearly_data/."
  echo "    Expected layout: yearly_data/2026/DEVIS260...../*.xlsm"
  exit 1
fi

echo ""
echo ">>> Years discovered in yearly_data/: $(echo $YEARS | tr '\n' ' ')"

# ── Step 1: refresh catalogues from the latest DEVIS BDD ─────────
echo ""
echo ">>> [1/4] Syncing blocks.json + armoires.json from latest DEVIS"
python3 poc/sync_catalogues.py

# ── Step 2: re-parse Excel → JSON for each discovered year ───────
for YEAR in $YEARS; do
  echo ""
  echo ">>> [2/4] Re-parsing $YEAR Excel → JSON"
  python3 poc/parse_yearly_data.py "$YEAR" --force | tail -10
done

# ── Step 3: 3-layer validation across ALL years ──────────────────
echo ""
echo ">>> [3/4] Running 3-layer validator (--strict)"
# validate_parsing.py auto-discovers years too — no flag needed
python3 poc/validate_parsing.py --full --strict $QUICK

# ── Step 4: file-size sanity check ───────────────────────────────
echo ""
echo ">>> [4/4] File-size sanity check"
ls -lh poc/data/yearly_projects_*.json poc/data/blocks.json poc/data/armoires.json poc/data/historical_quotes.json poc/data/accessories_rules.json

# ── Summary ──────────────────────────────────────────────────────
echo ""
echo "==========================================================="
echo " ✓ ALL CHECKS PASSED — safe to push"
echo "==========================================================="
echo " Reminder before pushing:"
echo "   • DO commit the regenerated JSONs (poc/data/yearly_projects_*.json)"
echo "   • DO commit blocks.json and armoires.json if they changed"
echo "   • DO NOT commit poc/chroma_db/ (gitignored — Render rebuilds it)"
echo "   • DO NOT commit yearly_data/ (gitignored — proprietary)"
echo "==========================================================="
