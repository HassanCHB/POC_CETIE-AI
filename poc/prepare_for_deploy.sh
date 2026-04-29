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

# ── Step 1: refresh catalogues from the latest DEVIS BDD ─────────
echo ""
echo ">>> [1/4] Syncing blocks.json + armoires.json from latest DEVIS"
python3 poc/sync_catalogues.py

# ── Step 2: re-parse Excel → JSON (force, in case of new DEVIS) ──
echo ""
echo ">>> [2/4] Re-parsing 2022 Excel → JSON"
python3 poc/parse_yearly_data.py 2022 --force | tail -10

echo ""
echo ">>> [2/4] Re-parsing 2026 Excel → JSON"
python3 poc/parse_yearly_data.py 2026 --force | tail -10

# ── Step 3: 3-layer validation ───────────────────────────────────
echo ""
echo ">>> [3/4] Running 3-layer validator (--strict)"
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
