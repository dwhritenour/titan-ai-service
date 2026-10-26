# Production Control — How-To Guide
Owner: Dave · App: Production Control · Updated: 2026-08-07 (DRAFT — Dave review)

## What this app is for
Production Control is the office app for running work orders through the shop: it creates work orders for non-standard straining-element configurations, defines each order's **routing** (which departments it visits, in what order), releases work to the floor, tracks progress, and manages the PC-created part master. Department boards (SE, Inspection, Assembly…) only ever see what this app has released to them.

## Who uses it
Production Control office staff. Runs in a browser on office PCs.

## How do I …

### How do I see the work order queue?
Open **Work Orders - Straining Element Department** (the condensed list). It shows active orders only, with clickable count filters across the top — click a count to filter to that status, **Clear Filters** to reset, **Refresh Work Orders** to reload. Click a WO to open its details.

### How do I create work orders for non-standard configurations?
Work orders are created automatically: the scan compares ordered configurations against the standard defaults on sales order lines and creates a WO for each non-standard one — a line whose ordered configuration differs from the standard default; these carry wo_type **Non-Standard** (numbered WO-YYYY-NNNN). It runs on the 15-minute data refresh, or on demand via the scan button. You'll rarely make one by hand.

### How do I set a routing and release a work order?
1. Open the work order and go to its **Routing** editor.
2. The SKU's default routing template loads if one exists. Adjust it: **+ Add Step** for each department step, reorder as needed, and use **SKU Notes** / **Sales Order Notes** to write the instruction lines the floor will see on their boards.
3. Press **Save Routing & Release**. The routing is captured onto this work order (later template changes won't alter it), the WO becomes **Released**, and its first step appears on that department's board.
- If you changed the routing, the app asks whether to update the SKU's default template too — say yes only if this is the new normal for that SKU.

### How do I track where a work order is?
Open **Routing** status for the WO — it shows each step, who did it, and timestamps as departments complete their steps. The department boards feed this live.

### How do I handle rework / send a WO back to a department?
On the routing status view, press **Reset Steps for Rework…** and choose the step to reset to (e.g. a failed inspection goes back to SE). The department's board picks it up again. Inspection failures do NOT move automatically — the inspector calls PC, and this is where you act.

### How do I manage PC-created SKUs?
Open **Part Master — PC-Created SKUs**. New non-standard parts minted here live in Nexus until exported: **Export batch only (not yet in e21)** produces the batch for e21 import. **Show retired** reveals retired parts; **Refresh** reloads.

### How do I watch customer orders?
Open **Sales Orders** (due list). Click the summary chips — **Late (Ship)**, **Due Today**, **Rush Jobs** — to filter instantly; click a WO number to jump to it. Data refreshes from e21 about every 15 minutes.

### How do I print the paperwork?
From a work order, generate the **WO packet PDF** (traveler) — it includes the routing and notes the floor needs. Reprint any time.

### Do notifications happen on their own?
Yes — routing events (releases, completions, rework resets) send SMS notifications to the configured recipients. Nothing to do per-order; if numbers need changing, that's an admin task — ask Dave.

## When something looks wrong
- **A WO isn't on a department board:** it isn't Released, or that department isn't the current step — check the routing status.
- **Floor says a completed step still shows:** boards refresh on a timer; have them refresh. If it persists, check whether the step actually completed in routing status.
- **A non-standard config didn't create a WO:** it may match the standard default exactly (no WO needed) or already have one — check the WO list first.
- **Released the wrong routing:** if the first step hasn't started, reset/adjust via rework; once work has begun, coordinate with the departments before changing anything.

## Who to ask
Dave Whritenour.
