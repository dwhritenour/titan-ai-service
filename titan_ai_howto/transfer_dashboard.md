# Transfer App — How-To Guide
Owner: Dave · App: Transfer Dashboard · Updated: 2026-08-07

## What this app is for
The Transfer Dashboard moves inventory from the Hub to Starlite. The AI
suggests what to transfer; a person approves or rejects each suggestion,
packs the approved items onto truck trips, and the driver confirms
delivery. It also holds the Starlite-side review pages (ABC Class,
Min/Max, Work Orders, Sales Orders).

## Who uses it
Office staff (transfer review, Min/Max, ABC, Sales Orders), the Hub team
(pick lists), and the truck driver (Deliver Trip page, phone or tablet).
Navigation is the sidebar on the left: **The Hub Facility**, **Forecasts**,
**Starlite Facility**, **Administration** sections.

## How do I …

### How do I review the AI's transfer suggestions?
1. Open **Transfer Form** (this is the page the app starts on).
2. Optional: press **Run AI Review** to check for new candidates. Wait for
   the "Review complete" message. (After the first run the button reads
   **Run Review Now**.)
3. On each row, pick **Approve**, **Reject**, or **Pause** in the
   **Decision** dropdown. You can edit the **Transfer Quantity** first.
   If you pick **Reject**, a date picker appears — set it to snooze the
   SKU until that date, or leave it blank for the automatic cooldown.
4. Press **Apply** and confirm. If you approved anything, the app offers
   to generate the **Pick List (PDF)** — say yes and the pick list
   downloads. Those rows become **Applied**.
- An amber SKU means the row is Paused; light red means paused more than
  3 days. A dark-orange bold SKU with "POSSIBLE DUPLICATE" in the
  reasoning box means check it against recent transfers before approving.

### How do I build truck trips?
1. Open **Trip Editor** and press **Optimizer**. If a pending batch
   already exists, the app asks whether to consolidate and re-optimize —
   usually say yes.
2. Pick the batch under **Select Batch Number**.
3. Adjust **Qty**, **Trip Date**, **Trip Time**, and **Trip #** per row.
   Watch **Trip Summary (Capacity Check)** — Vol % and Wt % over 100 mean
   the truck is overloaded.
4. Tick the rows to ship (or **Select All SKUs** — rows start unchecked),
   then press **Finalize Trips** and confirm. The pick list PDF(s)
   download automatically. Finalizing only some rows requires a
   **Carve Date**; the rest return to the queue for re-packing.

### How do I remove a SKU the Hub can't fulfill?
In **Trip Editor**, type **0** in that row's **Qty** and tab out. Confirm
"Remove SKU and Cancel Recommendation?" The recommendation is Cancelled
and will NOT come back to the queue. For everything the Hub shows zero
stock on, press **Clear Zero Stock** instead — a fresh recommendation is
created automatically when stock returns, so no demand is lost.

### How do I record a delivery (driver)?
1. Open **Deliver Trip** and tap **Deliver** on your trip.
2. Adjust the **Delivered** quantity on any line that differs from
   **Planned**, and add a **Note** (e.g. "Short 2").
3. Tap **Confirm Delivery**. If anything differed, the app tells you the
   Hub Manager will be notified. You'll see "Delivery recorded".

### How do I look up a past transfer or reprint a pick slip?
Open **SKU Processed**. Filter by SKU, date range, or status, then press
**Search SKU**. Click **Click for Notes** on a row to read its notes, or
**Reprint Slip** to re-download the picking slip (available for Applied,
Trip_Assigned, Finalized, or Delivered rows). **Export Excel/CSV** saves
the filtered list.

### How do I see what's blocked at the Hub?
Open **SKU Zero Stock**. This read-only page lists SKUs with demand that
the Hub can't cover; a bold red **Empty** flag means the Hub has none at
all. Sort by **Urgency (most pressing)** to see what needs restocking
first.

### How do I review Min/Max changes?
1. Open **Min/Max Qty**, press **Run AI Review**, and wait.
2. Set each row's **Decision** to **Approve**, **Reject**, or **Modify**
   (Modify requires override values and a reason), or use
   **Approve All Pending** / **Reject All Pending**.
3. Press **Apply Decisions** to record your choices — this does NOT
   change production yet.
4. Press **Apply to Production** to commit the approved/modified values.
- One-off change for a single SKU: use the **SKU Browser** panel, find
  the SKU, fill **Override Min** / **Override Max** / the reason, press
  **Submit Override**, then **Apply to Production**.

### How do I review ABC class changes?
Open **ABC Class**. Same pattern as Min/Max: **Run AI Review**, set
**Approve**/**Reject** per row, **Apply Decisons** (button is spelled
that way), then **Apply to Production**. Green PROMOTION rows move a SKU
up; orange DEMOTION rows move it down.

### How do I check sales orders due?
Open **Sales Orders**. Click the summary chips to filter instantly —
**Late (Ship)**, **Due Today**, **Rush Jobs**, etc. Click a WO number to
jump to that work order, or **Order Details** for the full popup with
notes and backorder info. Data refreshes from e21 every 15 minutes.

## When something looks wrong
- A SKU you expect isn't in Transfer Recommendations: it may be Rejected
  (snoozed/cooldown), Paused, already Applied, or blocked by an old open
  transfer order in e21 — check **SKU Processed** first.
- **Finalize Trips** says "No SKUs selected": tick the row checkboxes —
  they start unchecked.
- Pick list didn't download after Apply: the rows stayed Approved but not
  Applied; re-run Apply, or reprint later from **SKU Processed** once
  Applied.
- Trip missing on **Deliver Trip**: trips only appear there after
  **Finalize Trips** in the Trip Editor.
- **Apply Decisions** on Min/Max or ABC didn't change production values:
  that button only records decisions — press **Apply to Production**.

## Who to ask
Dave Whritenour.
