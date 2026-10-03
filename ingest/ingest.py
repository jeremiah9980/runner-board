#!/usr/bin/env python3
"""
Runner Board nightly ingest.

Drive "01 Inbox"  ->  extract datapoints (OCR sidecar first, Claude vision if needed)
                  ->  dedupe against docs/data/*.json
                  ->  append rows, write ledger/YYYY-MM-DD.csv
                  ->  move Drive files to "03 Processed" / "04 Needs Review"
                  ->  write docs/data/pipeline.json

Environment (set as GitHub Actions secrets / env):
  ANTHROPIC_API_KEY          Anthropic API key
  GDRIVE_SERVICE_ACCOUNT     Service-account JSON (the whole file, as a string)
  DRIVE_INBOX_ID             Folder IDs (defaults below are Jeremiah's "Runner Board" folder)
  DRIVE_EXTRACTED_ID
  DRIVE_PROCESSED_ID
  DRIVE_REVIEW_ID
  CLAUDE_MODEL               default claude-sonnet-4-5 (cheap enough for nightly vision)
  DRY_RUN                    "1" = extract and print, write nothing, move nothing
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
import anthropic

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data"
LEDGER = ROOT / "ledger"
TZ = ZoneInfo("America/Chicago")

FOLDERS = {
    "inbox": os.environ.get("DRIVE_INBOX_ID", "10XT-zmJInPWhV2cuwu0IarZQD8PM29UH"),
    "extracted": os.environ.get("DRIVE_EXTRACTED_ID", "1bGSrXT23nZDQUANjC31_9f1M9AGbG4pl"),
    "processed": os.environ.get("DRIVE_PROCESSED_ID", "1_z7PAGiL_qFiEk88hVTo4mSxEpzwG-sj"),
    "review": os.environ.get("DRIVE_REVIEW_ID", "1HlEE8vOLH1E-IP9zR8b6FNGcDFluvX40"),
}
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5")
DRY = os.environ.get("DRY_RUN") == "1"
MAX_IMAGE_BYTES = 3_500_000

APPS = {"DD": "DoorDash", "FV": "Favor", "UE": "Uber Eats", "FLEX": "Amazon Flex", "IC": "Instacart"}
NAME_RE = re.compile(r"^(?P<runner>[A-Za-z0-9]+)_(?P<app>DD|FV|UE|FLEX|IC|EXP|OFFER|META)_(?P<date>\d{4}-\d{2}-\d{2})(?:_(?P<n>\d+))?\.(?P<ext>jpe?g|png|txt|pdf|csv)$", re.I)

CSV_HEADER = ["type", "runner", "app", "date", "start", "end", "hours", "base", "tips", "fee", "deliveries",
              "miles", "pay", "minutes", "accepted", "category", "amount", "note", "source_file", "confidence"]

EXTRACT_SYSTEM = """You extract gig-work earnings datapoints from phone screenshots (or their OCR text) of DoorDash Dasher, Favor Runner, Uber Driver (Eats), Amazon Flex and Instacart Shopper apps, plus offer cards and expense receipts.
Return ONLY a JSON object, no prose, with this shape:
{"kind":"shift"|"offer"|"expense"|"unknown",
 "app":"DD"|"FV"|"UE"|"FLEX"|"IC"|null,
 "date":"yyyy-MM-dd"|null,
 "start":"HH:mm"|null, "end":"HH:mm"|null,
 "hours":number|null,          // dash/online time in hours, decimal
 "active":number|null,         // active / on-trip hours if shown
 "base":number|null,           // base pay + peak pay + promotions (everything except customer tips)
 "tips":number|null,
 "total":number|null,          // the app's own total, as shown
 "deliveries":number|null,     // deliveries / trips / batches / packages
 "miles":number|null,          // only if the app shows miles
 "pay":number|null, "offer_miles":number|null, "minutes":number|null, "accepted":true|false|null,   // offers only
 "category":string|null, "amount":number|null, "merchant":string|null,   // expenses only
 "confidence":"high"|"medium"|"low",
 "reason":string}              // one line: what you read it from, or why confidence is low
Rules: never guess a number that is not on the screen; use null. If base+tips differs from total by more than 0.05, set confidence to "low" and say so in reason. Times are local 24h. A screen showing a week or multiple days (not a single day/dash) is "unknown" with reason "multi-day summary"."""


# ---------------------------------------------------------------- helpers
def now_ct() -> datetime:
    return datetime.now(TZ)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def load_json(name: str, default):
    p = DATA / name
    if not p.exists():
        return default
    return json.loads(p.read_text())


def save_json(name: str, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def hm_to_dec(s: str | None):
    if not s:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})$", s.strip())
    if not m:
        return None
    return int(m.group(1)) + int(m.group(2)) / 60


def num(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- drive
def drive():
    raw = os.environ["GDRIVE_SERVICE_ACCOUNT"]
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_inbox(svc):
    files, token = [], None
    while True:
        r = svc.files().list(q=f"'{FOLDERS['inbox']}' in parents and trashed = false",
                             fields="nextPageToken, files(id,name,mimeType,size,createdTime)",
                             pageSize=200, pageToken=token).execute()
        files += r.get("files", [])
        token = r.get("nextPageToken")
        if not token:
            return files


def download(svc, file_id: str) -> bytes:
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


def move(svc, file_id: str, dest: str):
    if DRY:
        return
    f = svc.files().get(fileId=file_id, fields="parents").execute()
    svc.files().update(fileId=file_id, addParents=dest,
                       removeParents=",".join(f.get("parents", [])), fields="id").execute()


def upload_csv(svc, name: str, text: str) -> str | None:
    if DRY:
        return None
    media = MediaIoBaseUpload(io.BytesIO(text.encode()), mimetype="text/csv")
    f = svc.files().create(body={"name": name, "parents": [FOLDERS["extracted"]],
                                 "mimeType": "application/vnd.google-apps.spreadsheet"},
                           media_body=media, fields="id,webViewLink").execute()
    return f.get("webViewLink")


# ---------------------------------------------------------------- extraction
def extract(client: anthropic.Anthropic, hint: dict, ocr_text: str | None, image: bytes | None, mime: str | None) -> dict:
    content = []
    ctx = f"Filename hints: runner={hint.get('runner')}, app={hint.get('app')}, date={hint.get('date')}."
    if ocr_text:
        content.append({"type": "text", "text": ctx + "\nOCR text of the screenshot:\n" + ocr_text[:6000]})
    if image is not None:
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime or "image/jpeg",
                                                     "data": base64.b64encode(image).decode()}})
        content.append({"type": "text", "text": ctx + "\nExtract from the screenshot."})
    if not content:
        return {"kind": "unknown", "confidence": "low", "reason": "no content"}
    msg = client.messages.create(model=MODEL, max_tokens=600, system=EXTRACT_SYSTEM,
                                 messages=[{"role": "user", "content": content}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"kind": "unknown", "confidence": "low", "reason": "model returned non-JSON: " + text[:120]}


def parse_meta(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


# ---------------------------------------------------------------- main
def main():
    runners = load_json("runners.json", [])
    shifts = load_json("shifts.json", [])
    offers = load_json("offers.json", [])
    expenses = load_json("expenses.json", [])
    runner_names = {r["name"].lower(): r["name"] for r in runners}

    def match_runner(n: str | None):
        if not n:
            return None
        lo = n.lower()
        if lo in runner_names:
            return runner_names[lo]
        for k, v in runner_names.items():
            if k.startswith(lo) or lo.startswith(k):
                return v
        return None

    svc = drive()
    client = anthropic.Anthropic()
    files = list_inbox(svc)
    log(f"inbox: {len(files)} files")
    status = {"lastRun": now_ct().strftime("%Y-%m-%d %H:%M CT"), "filesProcessed": 0, "shiftsAdded": 0,
              "offersAdded": 0, "expensesAdded": 0, "skippedDuplicates": 0, "needsReview": 0,
              "sheetUrl": None, "summary": ""}
    if not files:
        status["summary"] = "Inbox empty."
        if not DRY:
            save_json("pipeline.json", status)
        print(json.dumps(status, indent=1))
        return

    by_name = {f["name"]: f for f in files}
    # group sidecars: base name -> {image, txt}
    groups: dict[str, dict] = {}
    metas: dict[tuple, dict] = {}   # (runner, date) -> meta dict
    for f in files:
        m = NAME_RE.match(f["name"])
        base = f["name"].rsplit(".", 1)[0]
        g = groups.setdefault(base, {"hint": {}, "files": []})
        g["files"].append(f)
        if m:
            g["hint"] = {k: (v.upper() if k == "app" else v) for k, v in m.groupdict().items() if v}
            if m.group("app").upper() == "META":
                g["is_meta"] = True
        ext = f["name"].rsplit(".", 1)[-1].lower()
        if ext in ("jpg", "jpeg", "png"):
            g["image"] = f
        elif ext == "txt":
            g["txt"] = f
        elif ext in ("pdf", "csv"):
            g["doc"] = f

    # pass 1: META files
    for base, g in list(groups.items()):
        if g.get("is_meta") and g.get("txt"):
            meta = parse_meta(download(svc, g["txt"]["id"]).decode(errors="ignore"))
            r = match_runner(meta.get("runner") or g["hint"].get("runner"))
            d = meta.get("date") or g["hint"].get("date")
            if r and d:
                metas[(r, d)] = meta
            g["meta_done"] = True

    ledger_rows: list[dict] = []
    review_notes: list[str] = []
    new_by_day: dict[tuple, list] = {}

    def is_dup_shift(rec):
        return any(s["runner"] == rec["runner"] and s["date"] == rec["date"] and s["app"] == rec["app"]
                   and abs((s.get("gross", 0) + s.get("tips", 0)) - (rec["gross"] + rec["tips"])) <= 0.05 for s in shifts)

    def is_dup_offer(rec):
        return any(o["runner"] == rec["runner"] and o["date"] == rec["date"] and o["app"] == rec["app"]
                   and abs(o["pay"] - rec["pay"]) <= 0.05 and abs(o.get("miles", 0) - rec["miles"]) <= 0.1 for o in offers)

    def is_dup_exp(rec):
        return any(e["runner"] == rec["runner"] and e["date"] == rec["date"] and abs(e["amount"] - rec["amount"]) <= 0.01 for e in expenses)

    # pass 2: everything else
    for base, g in groups.items():
        if g.get("is_meta"):
            continue
        hint = g["hint"]
        ocr = download(svc, g["txt"]["id"]).decode(errors="ignore") if g.get("txt") else None
        image, mime = None, None
        img = g.get("image")
        if img and (not ocr or len(ocr.strip()) < 40):
            size = int(img.get("size") or 0)
            if size > MAX_IMAGE_BYTES:
                review_notes.append(f"{img['name']}: image too large ({size} bytes); shortcut should resize to 900px JPEG")
                for f in g["files"]:
                    move(svc, f["id"], FOLDERS["review"])
                status["needsReview"] += 1
                continue
            image = download(svc, img["id"])
            mime = img.get("mimeType") or "image/jpeg"
        if not ocr and image is None and not g.get("doc"):
            continue
        if g.get("doc") and not ocr and image is None:
            review_notes.append(f"{g['doc']['name']}: statements/PDF not auto-parsed yet")
            move(svc, g["doc"]["id"], FOLDERS["review"])
            status["needsReview"] += 1
            continue

        if hint.get("app") == "OFFER" and ocr and "pay=" in ocr:
            kv = parse_meta(ocr)   # Offer Snap writes key=value lines; no model call needed
            res = {"kind": "offer", "app": (kv.get("app") or "").upper() or None, "date": kv.get("date"),
                   "pay": num(kv.get("pay")), "offer_miles": num(kv.get("miles")), "minutes": num(kv.get("minutes")),
                   "accepted": str(kv.get("accepted", "")).lower() in ("yes", "y", "true", "1"),
                   "start": kv.get("time"), "confidence": "high", "reason": "Offer Snap key=value file"}
        else:
            res = extract(client, hint, ocr, image, mime)
        # second chance with the image if OCR alone was weak
        if res.get("confidence") == "low" and img and image is None and int(img.get("size") or 0) <= MAX_IMAGE_BYTES:
            image = download(svc, img["id"])
            res = extract(client, hint, ocr, image, img.get("mimeType") or "image/jpeg")

        runner = match_runner(hint.get("runner"))
        app = (hint.get("app") if hint.get("app") in APPS else None) or (res.get("app") if res.get("app") in APPS else None)
        date = hint.get("date") or res.get("date")
        kind = res.get("kind", "unknown")
        if hint.get("app") == "EXP":
            kind = "expense"
        if hint.get("app") == "OFFER":
            kind = "offer"
        conf = res.get("confidence", "low")
        src = (img or g.get("txt") or g.get("doc"))["name"]
        row = {k: "" for k in CSV_HEADER}
        row.update(type=kind, runner=runner or hint.get("runner", ""), app=app or "", date=date or "",
                   source_file=src, confidence=conf, note=res.get("reason", ""))

        ok = runner and date and conf in ("high", "medium") and kind in ("shift", "offer", "expense")
        if kind in ("shift", "offer") and not app:
            ok = False
        if not ok:
            row["note"] = ("unknown runner; " if not runner else "") + (res.get("reason") or "")
            ledger_rows.append(row)
            review_notes.append(f"{src}: {row['note']}")
            for f in g["files"]:
                move(svc, f["id"], FOLDERS["review"])
            status["needsReview"] += 1
            continue

        ts = datetime.now(timezone.utc).isoformat()
        if kind == "shift":
            start, end = hm_to_dec(res.get("start")), hm_to_dec(res.get("end"))
            hours = num(res.get("hours"))
            if start is not None and end is not None and not hours:
                hours = round((end - start) % 24, 2)
            base_pay = num(res.get("base")) or 0.0
            tips = num(res.get("tips")) or 0.0
            if not base_pay and num(res.get("total")):
                base_pay = round(num(res["total"]) - tips, 2)
            rec = {"id": f"p_{date.replace('-', '')}_{runner.lower()}_{app.lower()}_{len(shifts) + 1}",
                   "runner": runner, "app": app, "date": date, "hours": hours or 0,
                   "active": num(res.get("active")) or 0, "gross": base_pay, "tips": tips, "fee": 0.0,
                   "deliveries": int(num(res.get("deliveries")) or 0), "miles": num(res.get("miles")) or 0.0,
                   "note": "", "src": "pipeline", "sourceFile": src, "confidence": conf, "createdAt": ts}
            if start is not None:
                rec["start"] = start
            if end is not None:
                rec["end"] = end
            row.update(start=res.get("start") or "", end=res.get("end") or "", hours=rec["hours"], base=base_pay,
                       tips=tips, deliveries=rec["deliveries"], miles=rec["miles"])
            if is_dup_shift(rec):
                row["note"] = "duplicate — not loaded"; status["skippedDuplicates"] += 1
            else:
                shifts.append(rec); status["shiftsAdded"] += 1
                new_by_day.setdefault((runner, date), []).append(rec)
        elif kind == "offer":
            rec = {"id": f"p_{date.replace('-', '')}_{runner.lower()}_{app.lower()}_o{len(offers) + 1}",
                   "runner": runner, "app": app, "pay": num(res.get("pay")) or 0.0,
                   "miles": num(res.get("offer_miles")) or 0.0, "minutes": int(num(res.get("minutes")) or 0),
                   "accepted": bool(res.get("accepted")), "date": date, "time": res.get("start") or "",
                   "ts": f"{date}T{res.get('start') or '12:00'}:00", "note": "", "src": "pipeline", "sourceFile": src}
            row.update(pay=rec["pay"], miles=rec["miles"], minutes=rec["minutes"], accepted="yes" if rec["accepted"] else "no")
            if is_dup_offer(rec):
                row["note"] = "duplicate — not loaded"; status["skippedDuplicates"] += 1
            else:
                offers.append(rec); status["offersAdded"] += 1
        else:
            rec = {"id": f"p_{date.replace('-', '')}_{runner.lower()}_e{len(expenses) + 1}", "runner": runner,
                   "date": date, "category": (res.get("category") or "other").lower(),
                   "amount": num(res.get("amount")) or 0.0, "note": res.get("merchant") or "",
                   "src": "pipeline", "sourceFile": src, "createdAt": ts}
            row.update(category=rec["category"], amount=rec["amount"], note=rec["note"])
            if is_dup_exp(rec):
                row["note"] = "duplicate — not loaded"; status["skippedDuplicates"] += 1
            else:
                expenses.append(rec); status["expensesAdded"] += 1

        ledger_rows.append(row)
        for f in g["files"]:
            move(svc, f["id"], FOLDERS["processed"])
        status["filesProcessed"] += len(g["files"])

    # apply META odometer miles + fees to the day's new shifts
    for (runner, date), recs in new_by_day.items():
        meta = metas.get((runner, date))
        if not meta:
            for r in recs:
                if not r["miles"]:
                    r["note"] = (r["note"] + " no odometer").strip()
            continue
        try:
            odo = float(meta.get("odo_end", 0)) - float(meta.get("odo_start", 0))
        except ValueError:
            odo = 0
        total_h = sum(r["hours"] for r in recs) or len(recs)
        if odo > 0:
            for r in recs:
                r["miles"] = round(odo * ((r["hours"] or 1) / total_h), 1)
        try:
            recs[0]["fee"] = float(meta.get("fees", 0) or 0)
        except ValueError:
            pass
    for g in groups.values():
        if g.get("is_meta"):
            for f in g["files"]:
                move(svc, f["id"], FOLDERS["processed"])
            status["filesProcessed"] += len(g["files"])

    # ledger CSV (repo + Drive sheet)
    run_day = now_ct().strftime("%Y-%m-%d")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_HEADER)
    w.writeheader(); w.writerows(ledger_rows)
    csv_text = buf.getvalue()
    if not DRY:
        LEDGER.mkdir(exist_ok=True)
        (LEDGER / f"{run_day}.csv").write_text(csv_text)
        status["sheetUrl"] = upload_csv(svc, f"Runner Ledger {run_day}", csv_text)
        save_json("shifts.json", shifts); save_json("offers.json", offers); save_json("expenses.json", expenses)

    parts = [f"{status['shiftsAdded']} shifts, {status['offersAdded']} offers, {status['expensesAdded']} expenses loaded"]
    if status["skippedDuplicates"]:
        parts.append(f"{status['skippedDuplicates']} duplicates skipped")
    if review_notes:
        parts.append("Needs review: " + "; ".join(review_notes[:5]))
    status["summary"] = ". ".join(parts) + "."
    if not DRY:
        save_json("pipeline.json", status)
    print(json.dumps(status, indent=1))


if __name__ == "__main__":
    main()
