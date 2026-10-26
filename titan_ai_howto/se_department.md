# SE Department (v2.0) — How-To Guide
Owner: Dave · App: SE Dept App v2.0 · Updated: 2026-08-07 (DRAFT — Dave review)

## What this app is for
The SE Department board is the shop-floor app for the Straining Element department: supervisors triage and assign released work orders; operators work them at a station with big Start/Stop/Complete buttons that also record time on the job. Only work orders that Production Control has **Released** to SE appear here.

## Who uses it
SE supervisors and operators, on the shared department kiosk/tablets. Office staff use the Completed pages for lookups.

## How do I …

### How do I get to my screen?
The app opens on **SE Department v2.0** (kiosk home). Tap your **Operator Name** to go to your station, or **Supervisor View** for the board.

### How do I assign work? (supervisor)
On **SE Department - Supervisor**, released work orders show as cards — WO number, SKU, quantity, due date, SO number. Cards are color-coded by due date and sorted oldest-first (FIFO tie-break); same-SO orders carry matching chips. Assign each card to an operator; **Hide Unassigned Work Orders** declutters the view when triaging is done. **Clear Filters** resets, **Refresh** reloads, **Completed Work Orders** and **Change Log** are in the sidebar.

### How do I work an order? (operator)
1. Your station (**SE Department -- Operator**) lists your assigned cards: **WO# + SKU + qty** with due date, SO#, and the instruction line PC wrote.
2. Press **Start** when you begin — the **Running / Paused** clock starts. Press **Stop** if you step away (time pauses), **Restart** to resume.
3. Press **View/Print** if you need the WO paperwork.
4. Press **Complete** when the work is done and confirm. The order leaves your station and moves to its next routing step (often Inspection).

### What happens after I complete?
The next department's board picks the order up automatically. If Inspection fails it later, Production Control resets it back to SE and it reappears on the supervisor board for re-triage (it does not return to the original operator automatically).

### How do I look up finished work?
**Completed Work Orders** lists finished orders with filters; the activity view shows the event history (who started/stopped/completed and when). A completed order that needs work again is re-opened by the office — it comes back as Released for re-triage.

## When something looks wrong
- **An order you expect isn't on the board:** PC hasn't released it, or SE isn't its current routing step — ask Production Control.
- **Started the wrong order:** Stop it (time pauses), start the right one. Tell your supervisor if the recorded time matters.
- **Completed by mistake:** the office can re-open it (it returns as Released to the supervisor board, not directly to you).
- **The clock reads Paused while you're working:** you pressed Stop at some point — press Restart.

## Who to ask
SE supervisor for day-to-day; Dave Whritenour for the app.
