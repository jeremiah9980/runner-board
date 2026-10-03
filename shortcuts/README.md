# iOS Shortcuts for runners

Three shortcuts. Build **Shift Snap** once on your phone, AirDrop it to each runner; they change one line (their name).
All three save into the shared Google Drive folder `Runner Board / 01 Inbox` (runners see it under *Shared with me*).

Requirements on each phone: iOS 17+, the Shortcuts app, Google Drive app signed in and enabled as a Files location
(Files → Browse → ⋯ → Edit → toggle **Google Drive**), and the gig apps installed.

Filename convention the pipeline relies on:

```
<Runner>_<APP>_<yyyy-MM-dd>_<n>.jpg     screenshot (resized to 900px wide, JPEG)
<Runner>_<APP>_<yyyy-MM-dd>_<n>.txt     on-device OCR of that screenshot
<Runner>_META_<yyyy-MM-dd>.txt          odometer + fees for the day
<Runner>_OFFER_<yyyy-MM-dd>_<n>.txt     one offer decision
<Runner>_EXP_<yyyy-MM-dd>_<n>.jpg       a receipt photo
APP codes: DD DoorDash · FV Favor · UE Uber Eats · FLEX Amazon Flex · IC Instacart
```

Token notation below: `[Name]` = tap the magic-variable token in the action, don't type the text.

---

## 1 · Shift Snap (end of shift, ~2 minutes)

| # | Action | Settings |
|---|--------|----------|
| 1 | **Text** | the runner's name exactly as in `docs/data/runners.json` (e.g. `Brian`) |
| 2 | **Set Variable** | `Runner` ← Text |
| 3 | **Date** → **Format Date** | Current Date, format Custom `yyyy-MM-dd` |
| 4 | **Set Variable** | `Day` ← Formatted Date |
| 5 | **Choose from List** | items `DD`, `FV`, `UE`, `FLEX`, `IC`; **Select Multiple** on; prompt "Which apps did you run?" |
| 6 | **Set Variable** | `Apps` ← Chosen Item(s) |
| 7 | **Repeat with Each** | `[Apps]` — steps 8–17 go inside |
| 8 | **Show Alert** | Title "Get the screen ready". Message: "Open [Repeat Item] → Earnings → today's summary. When it's on screen, swipe back here and tap OK." Show Cancel Button off |
| 9 | **Choose from Menu** on `[Repeat Item]` | cases `DD` → **Open App** DoorDash Dasher · `FV` → Favor Runner · `UE` → Uber Driver · `FLEX` → Amazon Flex · `IC` → Instacart Shopper |
| 10 | **Wait** | 3 seconds |
| 11 | **Take Screenshot** | — |
| 12 | **Resize Image** | input `[Screenshot]`, width `900`, height Auto |
| 13 | **Convert Image** | input `[Resized Image]`, JPEG, quality ≈60%, Preserve Metadata off |
| 14 | **Set Name** | `[Runner]_[Repeat Item]_[Day]_[Repeat Index].jpg` ("Don't include file extension" off) |
| 15 | **Save File** | Service Google Drive · **Ask Where to Save off** · path `Runner Board/01 Inbox` (runners: `Shared with me/01 Inbox`) · Overwrite on |
| 16 | **Extract Text from Image** | input `[Screenshot]` (the original) |
| 17 | **Set Name** → **Save File** | `[Runner]_[Repeat Item]_[Day]_[Repeat Index].txt`, same destination |
|   | *(end Repeat)* | |
| 18 | **Ask for Input** (Number) | "Odometer at START of shift" → **Set Variable** `OdoStart` |
| 19 | **Ask for Input** (Number) | "Odometer at END of shift" → **Set Variable** `OdoEnd` |
| 20 | **Ask for Input** (Number) | "Instant-pay fees today ($)", default `0` → **Set Variable** `Fees` |
| 21 | **Text** | six lines: `runner=[Runner]` / `date=[Day]` / `odo_start=[OdoStart]` / `odo_end=[OdoEnd]` / `fees=[Fees]` / `apps=[Apps]` |
| 22 | **Set Name** → **Save File** | `[Runner]_META_[Day].txt`, same destination |
| 23 | **Show Notification** | "Shift saved. Board updates overnight." |

Then: tap the name → **Add to Home Screen**. Optional: Settings → Action Button → Shortcut → Shift Snap.
First run: approve every "Allow…" prompt with **Always Allow**.

## 2 · Offer Snap (10 seconds, mid-shift)

| # | Action | Settings |
|---|--------|----------|
| 1–4 | same as Shift Snap | `Runner`, `Day` |
| 5 | **Choose from List** | `DD`, `FV`, `UE`, `FLEX`, `IC` (single) → `App` |
| 6 | **Ask for Input** (Number) | "Offer $" → `Pay` |
| 7 | **Ask for Input** (Number) | "Total miles" → `Miles` |
| 8 | **Ask for Input** (Number) | "Minutes" → `Min` |
| 9 | **Choose from List** | `yes`, `no`, prompt "Took it?" → `Took` |
| 10 | **Date** → **Format Date** | Custom `HH:mm` → `Time` |
| 11 | **Text** | `runner=[Runner]` / `date=[Day]` / `app=[App]` / `pay=[Pay]` / `miles=[Miles]` / `minutes=[Min]` / `accepted=[Took]` / `time=[Time]` |
| 12 | **Set Name** → **Save File** | `[Runner]_OFFER_[Day]_[Time].txt`, same destination (colon in time is fine on Drive) |

## 3 · Receipt Snap (one receipt, right now)

| # | Action | Settings |
|---|--------|----------|
| 1–4 | same | `Runner`, `Day` |
| 5 | **Take Photo** | Show Camera Preview on. Flatten the receipt, fill the frame, whole total visible. |
| 6 | **Resize Image** → **Convert Image** | width `1200` (receipts need more pixels than app screens), JPEG 70% |
| 7 | **Date** → **Format Date** | Custom `HHmm` → `Stamp` |
| 8 | **Set Name** → **Save File** | `[Runner]_EXP_[Day]_[Stamp].jpg`, same destination |

The job sorts each receipt into **order** (shop-and-deliver basket paid with the platform card — matched to the shift whose
hours contain the receipt time, never counted as an expense) or **expense** (your own fuel/parking/gear — added to the
tax deductions). You don't have to tell it which; the card, merchant and basket give it away.

## 4 · Receipt Batch (end of day, all receipts at once)

For runners who photograph receipts with the normal Camera app during the day and don't want to stop and run a shortcut each time.

| # | Action | Settings |
|---|--------|----------|
| 1–4 | same | `Runner`, `Day` |
| 5 | **Select Photos** | **Select Multiple** on. Prompt: pick every receipt from today. |
| 6 | **Repeat with Each** | `[Photos]` — steps 7–9 inside |
| 7 | **Resize Image** → **Convert Image** | 1200px, JPEG 70% |
| 8 | **Get Details of Images** | Date Taken → **Format Date** custom `HHmm` → `Stamp` (so the receipt keeps its real time for shift matching) |
| 9 | **Set Name** → **Save File** | `[Runner]_EXP_[Day]_[Stamp]_[Repeat Index].jpg`, same destination |
| 10 | **Show Notification** | "[Count] receipts sent." |

Tip: make an iOS Photos album "Receipts" and point Select Photos at it so the picker opens there.

## 5 · Earnings Scroll (screen recording — the easiest capture of all)

Instead of screenshots, record the earnings list while you scroll. The job pulls one frame per second, drops duplicates, and reads
every trip: time, pay, tip, toll, minutes, miles, pickup → drop-off. One 15-second recording covered three days of Uber Eats trips.

1. Control Center → **Screen Record** (add it under Settings → Control Center if missing). Tap it, wait for the 3-count.
2. Open the app's list: Uber Driver → Earnings → **Activity** (set the week filter); DoorDash → Earnings → tap the week → dash list;
   Instacart → Earnings → batch history. Scroll slowly top to bottom — about one screen per second — until "End of activities".
3. Stop the recording (red status bar → Stop). It saves to Photos.
4. Run **Video Snap** (below) to send it. Filename convention: `<Runner>_<APP>_<yyyy-MM-dd>_v<n>.mov` — the date is the day you recorded; the job reads the real dates from the day headers in the list.

### Video Snap

| # | Action | Settings |
|---|--------|----------|
| 1–4 | same as Shift Snap | `Runner`, `Day` |
| 5 | **Choose from List** | `DD`, `FV`, `UE`, `FLEX`, `IC` → `App` |
| 6 | **Select Photos** | Include Videos on; pick the recording(s). Select Multiple on. |
| 7 | **Repeat with Each** | `[Photos]` |
| 8 | **Set Name** → **Save File** | `[Runner]_[App]_[Day]_v[Repeat Index].mov`, destination `01 Inbox` |
| 9 | **Show Notification** | "Sent. Trips show up on the board overnight." |

Keep recordings under ~60 s; the job skips videos over 120 MB. If the list is long, record it in two passes (`_v1`, `_v2`) — duplicates are merged.

## Sharing a shortcut

Shortcut ⋯ → Share → AirDrop (or Copy iCloud Link and text it). Recipient taps **Add Shortcut**, then edits **step 1** to their own name. Nothing else changes.
