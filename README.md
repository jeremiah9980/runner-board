# Runner Board

Gig-work tracker for the family's runners (DoorDash, Favor, Uber Eats, Amazon Flex, Instacart).
Runners never type numbers: one iOS Shortcut after a shift → screenshots land in a shared Google Drive folder →
a nightly GitHub Actions job extracts the datapoints with Claude → rows are committed to `docs/data/*.json` →
the GitHub Pages dashboard re-reads them.

```
phone (Shift Snap) ──► Google Drive / Runner Board / 01 Inbox
                                   │  nightly 04:40 UTC  (.github/workflows/ingest.yml)
                                   ▼
                        ingest/ingest.py  ── Claude API (OCR text first, image if needed)
                                   │
          ┌────────────────────────┼─────────────────────────┐
          ▼                        ▼                         ▼
 docs/data/shifts.json     ledger/YYYY-MM-DD.csv       Drive: 02 Extracted (Google Sheet)
 offers.json, expenses.json  (audit trail)             03 Processed / 04 Needs Review
 pipeline.json
          │
          ▼
 GitHub Pages: docs/index.html  (read-only dashboard + "Should I take it?" calculator)
```

## Repo layout

| Path | What |
|------|------|
| `docs/index.html` | The dashboard (single file, no build). Served by GitHub Pages from `/docs`. |
| `docs/data/runners.json` | Who the runners are and their weekly goals. **Edit by hand.** Names must match the shortcut's step 1. |
| `docs/data/settings.json` | IRS mileage rate, tax set-aside %, $/mile floor, fallback $/hr target, week start (1 = Monday). **Edit by hand.** |
| `docs/data/shifts.json`, `offers.json`, `expenses.json` | Written by the pipeline. Fix a bad row here and commit. |
| `docs/data/pipeline.json` | Last run status; shown on the dashboard's "How it works" tab. |
| `ledger/` | One CSV per run — every extracted row incl. duplicates and review items, with source filename and confidence. |
| `ingest/ingest.py` | The job. `DRY_RUN=1` extracts and prints without writing or moving anything. |
| `shortcuts/README.md` | Build sheets for Shift Snap, Offer Snap, Receipt Snap. |

## Setup — line items

### A. Google Drive (one time, ~15 min)

1. The folder structure already exists in Jeremiah's Drive: `Runner Board / 01 Inbox · 02 Extracted · 03 Processed · 04 Needs Review`.
   Folder IDs are the defaults in `ingest.py`; override with `DRIVE_*_ID` env vars if you rebuild them.
2. Create a Google Cloud project (console.cloud.google.com) → **APIs & Services → Enable APIs** → enable **Google Drive API**.
3. **IAM & Admin → Service Accounts → Create** (name `runner-board-ingest`) → Keys → **Add key → JSON**. Download it. Never commit it.
4. Share each of the four folders with the service account's email (`runner-board-ingest@<project>.iam.gserviceaccount.com`) as **Editor**.
   Also share **only `01 Inbox`** with each runner's Google account as Editor.

### B. GitHub (one time, ~10 min)

5. Repo `jeremiah9980/runner-board`, private. Push this tree to `main`.
6. **Settings → Secrets and variables → Actions → New repository secret**:
   - `ANTHROPIC_API_KEY` — from console.anthropic.com (set a monthly spend limit; nightly runs cost cents).
   - `GDRIVE_SERVICE_ACCOUNT` — paste the entire JSON key file contents.
7. **Settings → Actions → General → Workflow permissions → Read and write** (the job commits data).
8. **Settings → Pages → Source: Deploy from a branch → `main` / `/docs`**. Note the URL. Send it to runners.
   ⚠ On a personal/Pro plan a Pages site from a private repo is still **publicly reachable** by URL (private Pages needs Enterprise).
   The page carries `noindex`, uses first names only, and the URL is unguessable — decide if that is acceptable, or put
   Cloudflare Access / a Netlify password in front of it.
9. **Actions → Runner Board nightly ingest → Run workflow** with *dry run* checked. Confirm it lists the inbox and prints JSON.
   Then run it un-checked once with a real file in the inbox.

### C. Data (5 min)

10. Edit `docs/data/runners.json`: one object per runner `{"name":"Brian","weeklyGoal":500,"apps":"DD, UE","active":true}`. Remove `Example`.
11. Delete the `Example` rows from `shifts.json`, `offers.json`, `expenses.json` (or leave them until real data arrives — they're tagged `src: example`).
12. Check `settings.json` → `mileageRate` against the current IRS standard mileage rate each January.

### D. Phones (per runner, ~10 min after you build the shortcut once)

13. Follow `shortcuts/README.md`. AirDrop the three shortcuts; runner edits step 1 (name) in each.
14. Runner does one shift, runs Shift Snap, you run the workflow manually, check the dashboard and `04 Needs Review`.

## Operating it

- **Bad row** → edit the JSON in `docs/data/`, commit. The ledger CSV tells you which screenshot it came from.
- **Needs Review pile-up** → open the file in `04 Needs Review`, read the numbers, add the row by hand to the JSON, move the file to `03 Processed`.
- **New app** → add its code to `APPS` in `ingest.py` and `docs/index.html`, add its screen to `EXTRACT_SYSTEM`, add a case to the shortcut.
- **Time change** → cron is UTC; `40 4` is 11:40 PM CDT / 10:40 PM CST. Change to `40 5` in November if it matters.
- **Cost** → one Claude call per screenshot (two if the OCR text was weak). A runner doing two apps a day ≈ 60 calls/month.
