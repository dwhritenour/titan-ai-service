# Hub Transfers v2.1 — How-To Guide
Owner: Dave · App: Hub Transfers v2.1 (https://titan-hub.anvil.app) · Updated: 2026-09-07

## What this app is for
Hub Transfers moves stock from the Hub to Starlite and keeps every step honest. The flow is **Recommend → Approve → Pick → Finalize → Load → Depart → Deliver → Receive**. The AI reviews what Starlite needs and recommends transfers; the Hub Manager approves them and builds picks; a Hub worker picks on the tablet; the dock finalizes a truck, loads it and departs it; the driver confirms delivery at Starlite; Starlite receives the e21 transfer order. Everything that can sit between steps shows on one **exceptions board**, with how long it has sat and how long until the system acts. The app also carries the review pages (Min/Max, ABC Class, Zero Stock, Processed) and System Admin.

## Who uses it
- **Hub Manager** — Transfer Recs, Pick Editor, the exceptions board, the review pages.
- **Hub workers** — the picking tablet (`#pick`).
- **Dock / shipping** — the Trip Editor (`#dock`): finalize, load, depart. The Hub Manager's job ends when a pick is complete; the dock owns the truck.
- **Driver** — the Deliver screen (`#deliver`) at Starlite.
- **Starlite** — receives the e21 transfer order (in e21, not in this app). This is the step that most often gets missed, and the app now says so.
- **Dave** — System Admin, parameters, texts.

The left sidebar navigates: Transfer Recs, Pick Editor, Trip Editor, Deliver, Exceptions, Processed, Zero Stock, ABC Class, Min/Max Qty, System Admin — plus **✦ Titan AI** and **Change Log**, which open other apps in a new tab. Stations bookmark the app URL with a hash (`#pick`, `#dock`, `#deliver`, `#exceptions`) and land on their screen directly.

## How do I …

### How do I work the Transfer Recs page? (Hub Manager)
The AI review runs on its own every 15 minutes and lists what Starlite should receive from the Hub, with a quantity and its reasoning. For each row pick a decision in the dropdown — **Approve** (optionally adjust the quantity), **Reject** (a snooze date appears: the SKU won't be re-raised until then), or **Pause** (park it; the AI stops re-reviewing it until you un-pause) — then press **Apply**. **Reject All** rejects every Pending row you can see. **Run review** forces a fresh AI pass now.

Two filters at the top narrow a long list: a **SKU** box and a **Status** dropdown (All / Pending / Paused / Warned). Decisions you've made on rows that are filtered out are kept and still sent by Apply — the count label tells you how many hidden decisions are going with it. Reject All only touches the rows you can see.

**Never approve a rec whose reasoning starts with "UNRECEIVED E21 TRANSFER … Do NOT approve".** It means an e21 transfer for that SKU shipped from the Hub more than **2 days** ago and Starlite has not received it. The stock is physically at Starlite or on the truck; approving would send a second one. Have Starlite receive the e21 order; the next review drops the warning and re-evaluates. These rows show as **Warned** in the status filter.

What the AI re-reviews: a rec is re-scored only when something real changed (Starlite availability, e21 in-transit, a warning raised or cleared), when a person touched it, or once a day for a refresh. Otherwise the numbers you see are refreshed but the AI's quantity and reasoning stand — so a rec does not wander from batch to batch.

### How do I build a pick? (Hub Manager)
1. Open **Pick Editor**. The **Unassigned Pool** lists approved transfer lines not yet on any pick.
2. Press **New Pick** to start a pick (it begins as a **Draft** — invisible to the floor).
3. Tick lines in the pool (or **Select All**) and press **Add Selected → Pick**. Adjust quantities on the pick's lines if needed; **Remove** takes a line back off.
4. Assign the worker, then press **Release**. The pick appears on that worker's tablet. **Print Pick Slip** if you want paper as well.
- A Released pick that sits untouched too long (about 4 hours) gets flagged as aging on the editor.
- Approved something by mistake? **Remove from pool** on the pool row sends the rec back to Pending on the Transfer Recs page (reject it there if you want the cooldown). It only works while no pick line is active for it.

### How do I pick on the tablet? (Hub worker)
1. On the **Hub Picking** screen (`#pick`), **Tap your name**. **My Picks** lists the picks released to you.
2. Tap a pick to open it. Work down the lines: confirm each quantity picked as you go.
3. If the shelf doesn't have enough, record the line **short** and pick the reason from the list (not found, insufficient stock, damaged, etc.). A short line closes that item short — it will NOT come back on this pick. Every short pick texts Inventory Control for a cycle count.
4. Picking over the plan is allowed up to **10%**; going over notifies the Hub Manager and needs a discrepancy reason.
5. The big button shows **COMPLETE PICK (n lines left)** until every line is resolved, then press **COMPLETE PICK** and confirm. The pick disappears from your list and its lines appear on the dock's staged panel.
- **Switch Worker** returns to the name screen; **← My Picks** backs out of a pick without finishing it (your progress is saved).

### How do I fix or undo a pick? (Hub Manager)
- **Cancel Pick** cancels a Draft or Released pick; its lines return to the Unassigned Pool.
- Made a mistake on a completed pick? Tick **Show recent completed (for Reopen)** and press **Reopen** on it — possible until one of its lines has ridden a finalized truck.
- A pick that was picked to zero and the rec is unresolved: cancel it with a note. Standing rule — nothing amber or red on the staged panel survives the next truck.

### How do I build and send a truck? (dock)
Open the **Trip Editor** (`#dock`). The flow is **FINALIZE → LOAD → DEPART** — finalize before reality, not after.
1. **Staged panel.** Every completed-pick line not yet on a truck, with qty, weight, volume, pick number, how long it has been staged, and its urgency. Tick the lines for this truck; the capacity summary (cubic feet and pounds against the truck limits) updates as you tick, before anything is committed. Press **FINALIZE TRUCK**: the trip is created and the **manifest** is ready to download and print.
2. **Load panel.** The same lines, with load actions: **✔ LOADED** when it's on the truck; **SHORT** when less went on than planned (choose the reason — the manager is texted and the remainder goes to a cycle count); **Remove** sends a line back to staged; **Undo** reverses a load action.
3. **TRUCK DEPARTED.** Refused until every line is resolved. Anything still marked staged needs a per-line "still at the Hub" acknowledgment — the server checks; the gate cannot be skipped. Departing stamps the ship date once and hands the truck to the driver's screen.
- Any active worker can run the dock; every action records who. One open truck per worker.
- The dock removes lines from trucks; it never cancels a recommendation. Those decisions belong to the Hub Manager.

### How do I record a delivery? (driver)
Open **Deliver** (`#deliver`), tap your name in **Delivering as…**, tap your trip, adjust any line that differs from what was loaded, add a note, and **Submit**. Differences text the Hub Manager. The trip becomes Delivered and every rec on it closes.

Delivered is not received. **Starlite must receive the e21 transfer order** for the stock to count at Starlite. Until they do, the app treats the goods as in transit — and after 2 days it starts warning (see Transfer Recs and the exceptions board).

### How do I use the exceptions board? (Hub Manager)
Open **Exceptions** (`#exceptions`). One grid, every place a transfer can get stuck, ordered by stage then age. **Age** is how long it has been open; **Left** is how long until the system acts — negative and red means overdue.
1. **Approved, not picked** — auto-cancelled after the threshold (5 days); the detector re-raises the SKU on the next batch. You can cancel earlier from the row.
2. **Picked, not loaded** — never auto-closed. After the threshold the Hub Managers get one digest text listing the lines, and the row shows OVERDUE until someone chooses **SHIPPED-CLOSE** (it went on a truck without the paperwork; close it, e21-verified receipts justify this) or **RETURN TO STOCK** (put it back; Inventory Control is texted for a cycle count).
3. **Departed, not delivered** — the truck left and the driver hasn't submitted. **CONFIRM DELIVERED** closes it with a date and a name.
4. **Open e21 transfer** — read-only. Starlite receives it, or the Hub ships it. This is where the 2-day warnings come from.
The board is the first screen to open on a Monday.

### How do I handle SKUs the Hub can't fill?
**Zero Stock** lists demand the Hub can't cover (bold red **Empty** = none at all). Shorts recorded during picking land the same way — a fresh recommendation is created when stock returns.

### How do I see what already happened?
**Processed** lists completed and cancelled transfers by batch; tap a row for its notes, and **Reprint Slip** re-prints a pick slip for a batch.

### How do I review Min/Max and ABC classes?
**Min/Max Qty** and **ABC Class** show the AI's recommended stocking levels and classifications with the reasoning; approve, adjust or reject each, and Apply. Classification never blocks demand fulfillment — a transfer is raised for any SKU Starlite needs, stocked or not; stocking levels only drive replenishment.

### What texts does the app send, and how do I stop them?
Texts go to the people tagged for each type in the contacts table (Dave maintains it — tell him who should get what): new recommendations (Hub Managers), pick exceptions and over-picks (Hub Managers), short picks and dock shortfalls (Inventory Control, cycle counts), load exceptions, delivery discrepancies, the picked-not-loaded digest, and the board's return-to-stock cycle count. Every text is logged.

One switch silences all of them: the **`sms_enabled`** row in Global Parameters. Set it to **0** (Dave, or anyone with SQL access to Nexus) and no text leaves the app, instantly, from any sender; set it to **1** to resume. When it's off, each would-be sender logs "NOT sent — kill switch is off", so a quiet phone is never a mystery.

### Where are the settings?
**System Admin** shows the stocking and truck parameters (lead time, safety days, service level, transfer horizon, truck capacity in ft³ and lb) and saves a change as soon as you leave the box. The operational switches live as rows in Global Parameters and are set by SQL. The ones that matter day to day: `sms_enabled` (the kill switch), `pick_overpick_cap_pct` (10), `e21_intransit_max_age_days` (2 — the unreceived-transfer rule), `pipeline_exception_days` (5 — the board's thresholds), `e21_tripwire_enabled` (the delivered-not-received alarm), `ai_review_enabled` and the AI re-review settings. Changes take effect on the next run; none need a redeploy.

## When something looks wrong
- **A worker doesn't see a pick:** it's probably still Draft — only **Released** picks reach the tablet. Check Pick Editor.
- **A line vanished from the pool:** it's on another pick, or its recommendation was cancelled/completed — check **Processed** or the exceptions board.
- **The tablet shows "No picks assigned right now":** nothing is Released to that worker; confirm the right name was tapped.
- **Pick won't complete:** every line must be resolved (picked, short, or removed by the manager) before COMPLETE PICK works.
- **TRUCK DEPARTED won't go:** a line is unresolved, or a staged line hasn't been acknowledged as still at the Hub. Resolve or acknowledge each one.
- **A rec says UNRECEIVED E21 TRANSFER:** don't approve it. Starlite has an e21 transfer to receive; the warning clears on the next review after they do.
- **The same SKU keeps coming back:** it was rejected without a snooze date, or the Hub short-picked it and stock returned. Reject with a date to snooze it.
- **Texts stopped:** check `sms_enabled` first, then the contact's tags in the contacts table.
- **Texts are wrong or noisy:** set `sms_enabled` to 0 and tell Dave. The app keeps working; only the phones go quiet.
- **Something has been "in transit" for a week:** it's on the exceptions board under stage 3 or 4. Either the driver never submitted (CONFIRM DELIVERED) or Starlite never received the e21 order (receive it in e21).

## Who to ask
Dave Whritenour (app + process). Hub Manager for day-to-day pick and rec questions. Starlite receiving for anything stuck at stage 4.
