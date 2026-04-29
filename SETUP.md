# CETIE AI Configurator — Contributor Setup

Onboarding guide for anyone joining the repo. Follow it once, then you can
add new DEVIS, regenerate the corpus, and push to production with confidence.

---

## 1 — Get the repo

```bash
git clone https://github.com/HassanCHB/POC_CETIE-AI.git
cd POC_CETIE-AI
git checkout amir          # the branch Render auto-deploys
```

If you get a 403 / *"Repository not found"*, ask Hassan to add you as a
collaborator with **Write** access. Use your exact GitHub username (case-insensitive).

---

## 2 — Activate the version-controlled git hooks (one-time, per machine)

This ensures the pre-push checks run automatically on every push.

```bash
git config core.hooksPath hooks
```

Verify:

```bash
git config core.hooksPath
# Should print: hooks
```

What this gives you: a fast pre-push gate that catches large files, accidentally
committed `chroma_db/`, secrets in commits, malformed JSON corpus. See `hooks/README.md`
for the full list.

---

## 3 — Install Python dependencies

You need **Python 3.11.5** (matches what Render uses). On macOS with Homebrew:

```bash
brew install python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r poc/requirements.txt
```

Or with `pyenv`:

```bash
pyenv install 3.11.5
pyenv local 3.11.5
python3 -m venv .venv && source .venv/bin/activate
pip install -r poc/requirements.txt
```

---

## 4 — Set up your local environment file

```bash
cp poc/.env.example poc/.env
```

Then open `poc/.env` and paste your real keys:

- `OPENAI_API_KEY` → from https://platform.openai.com/api-keys
- `ANTHROPIC_API_KEY` → from https://console.anthropic.com/settings/keys

`poc/.env` is gitignored — it never gets committed.

> **For production keys** (the ones the live Render service uses), don't put
> them here. They're set in the Render dashboard → Environment tab.

---

## 5 — Bring your own DEVIS data

The raw Excel files (`yearly_data/`) are **proprietary client data and are NOT
in the repo** (intentionally — see `.gitignore`). To work with the corpus:

1. Get the latest CETIE DEVIS folders from Hassan / the network share
2. Place them locally under:
   ```
   POC_CETIE-AI/
     yearly_data/
       2022/
         DEVIS2201100 ERIDIS .../
           DEVIS2201100 indice 1.xlsm
           ...
       2026/
         ...
   ```
3. Folder structure: each DEVIS in its own subfolder, with the `.xlsm` inside.

Note: 2022 files have a nested `2022/2022/` layout for historical reasons.
The parser handles both.

---

## 6 — Build (or refresh) the local corpus

If `poc/data/yearly_projects_*.json` files are already in the repo (they are),
you can skip the parse step and use them as-is. Otherwise — or whenever you
**add new DEVIS** or **a whole new year folder** — regenerate everything with:

```bash
bash poc/prepare_for_deploy.sh
```

This 4-step script:

1. Syncs `blocks.json` + `armoires.json` from the latest DEVIS BDD sheets
2. **Auto-discovers every year folder** in `yearly_data/` and re-parses each
   one into `poc/data/yearly_projects_<year>.json`. Drop a new `2027/` folder
   in and the script picks it up without any edits.
3. Runs the 3-layer validator (`validate_parsing.py --full --strict`) across
   ALL discovered years.
4. File-size sanity check.

Takes ~10 minutes total (the slow part is OpenAI embedding calls in layer 2).
Costs ~$0.05 in API.

After this and a successful push, Render auto-deploys. On boot the app
detects the new `yearly_projects_<year>.json` and incrementally builds the
ChromaDB collection for that year only — existing years' indexes are reused.

---

## 7 — Run locally to verify

```bash
cd poc
python3 app.py
```

Open http://localhost:5000 — you should see the login page.

Log in with the default `admin` account, or create a new user:

```bash
python3 poc/manage_users.py add yourname --role admin
```

---

## 8 — Workflow: push your changes

After editing code or refreshing the corpus:

```bash
# 1. Verify everything is healthy (10 min, optional but recommended)
bash poc/prepare_for_deploy.sh

# 2. Commit + push via GitHub Desktop (or CLI)
git add -A
git commit -m "your message"
git push
```

**The pre-push hook runs automatically** (~30 seconds). If it fails, it tells
you exactly what to fix. If it passes, the push proceeds.

Once the push lands on the `amir` branch, Render auto-deploys within 2 minutes.

---

## 9 — What's where

| Folder / file | Lives in git? | Purpose |
|---|---|---|
| `poc/*.py` | ✅ yes | Application code |
| `poc/templates/` | ✅ yes | HTML / CSS / JS |
| `poc/data/blocks.json` | ✅ yes | Component catalogue (synced from BDD) |
| `poc/data/armoires.json` | ✅ yes | Enclosure catalogue (synced from BDD) |
| `poc/data/yearly_projects_*.json` | ✅ yes | Parsed RAG corpus |
| `poc/data/historical_quotes.json` | ✅ yes | Curated example quotes |
| `poc/data/accessories_rules.json` | ✅ yes | 20 estimator rules |
| `poc/data/users.json` | ✅ yes | User accounts (hashed passwords only) |
| `poc/.env` | ❌ gitignored | Local API keys (never commit) |
| `poc/data/history.json` | ❌ gitignored | Runtime — created fresh on first run |
| `poc/data/feedback.json` | ❌ gitignored | Runtime |
| `poc/data/learned_rules.json` | ❌ gitignored | Runtime |
| `poc/data/sessions.json` | ❌ gitignored | Runtime auth tokens |
| `poc/chroma_db/` | ❌ gitignored | Vector index — regenerated locally on demand |
| `yearly_data/` | ❌ gitignored | Raw client Excel files (proprietary) |

In production (Render), the runtime files (history, feedback, sessions, users)
and the ChromaDB live on a persistent disk at `/var/cetie-state/`. They survive
every deploy. See `render.yaml` for details.

---

## 10 — Troubleshooting

### "Repository not found" when pushing
You're either not invited as a collaborator, or git is authenticated as the
wrong account. Check with:
```bash
git remote -v
git push       # error message will show which user git thinks you are
```

### "401 Unauthorized" on the live app after a fresh deploy
The frontend may have a stale token. In the browser console:
```javascript
localStorage.clear(); location.reload();
```
Then log in again.

### ChromaDB build fails locally with "OPENAI_API_KEY not set"
You forgot to copy `.env.example` → `.env` and fill in your keys. See step 4.

### Pre-push hook blocks every push with "chroma_db/ is tracked"
You have leftover ChromaDB files in git from before they were gitignored. Run:
```bash
git rm -r --cached poc/chroma_db
git commit -m "untrack chroma_db"
```
