# Git hooks for the CETIE AI Configurator

This directory holds version-controlled git hooks that run automatically at
key points in the workflow. They protect the team from common mistakes
(pushing huge files, committing secrets, breaking the JSON corpus) without
slowing down the everyday push cycle.

## One-time setup (per machine)

After cloning the repo, run **once**:

```bash
git config core.hooksPath hooks
```

This tells git to look in `hooks/` instead of the default `.git/hooks/` —
which means everyone on the team gets the same hooks just by pulling.

To verify it worked:

```bash
git config core.hooksPath
# Should print: hooks
```

## Hooks installed here

### `pre-push` — fast push gate

Runs in ~10–30 seconds before every `git push`. Catches:

| Check | Blocks push? |
|---|---|
| File > 100 MB in upcoming commits (GitHub rejects these) | ✗ blocked |
| File between 50-100 MB (GitHub warns) | ⚠ allowed |
| `poc/chroma_db/` tracked in git | ✗ blocked |
| `yearly_data/` tracked in git | ✗ blocked |
| Likely API key in staged content | ⚠ allowed (review) |
| `yearly_projects_*.json` malformed or empty | ✗ blocked |
| `blocks.json` / `armoires.json` malformed | ✗ blocked |

If it blocks you, the message tells you the exact fix.

To bypass once (e.g. for a known-safe commit): `git push --no-verify`

## Companion: thorough validation script

For full pre-deployment validation that includes ChromaDB embedding tests
(takes ~10 minutes, costs ~$0.05 in OpenAI calls), run manually:

```bash
bash poc/prepare_for_deploy.sh
```

This goes deeper than the pre-push hook:

1. Re-syncs blocks/armoires from latest DEVIS BDD
2. Re-parses all Excel → JSON
3. Runs the 3-layer validator including the embed test
4. File-size sanity check

Use it before any "release" push (e.g. when invitations go out to testers).
The pre-push hook is what runs every push; this script is what you run when
you want maximum confidence.
