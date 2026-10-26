# SE Inspection — How-To Guide
Owner: Chuck · App: SE Inspection · Updated: 2026-08-07

## What this app is for

SE Inspection is where a straining element gets checked before it moves on.
The inspector picks the work order off the list, times the inspection,
records what was measured and verified, adds photos, and marks it **Pass**
or **Fail**. A Pass tells Production Control the Inspection step is done and
the work order moves to whatever comes next; a Fail is recorded and stays put
until Production Control sends it back to SE.

The work orders you see here are the ones Production Control's routing has
made ready for Inspection — nothing else shows up.

## Who uses it

SE inspectors, on a tablet at the inspection bench (it also works on a
desktop browser). Office staff use the **Recent** page to look up past
inspections and print the PDF.

Navigation is the sidebar on the left: **Inspection** and **Recent**, with a
**Refresh** button and a badge underneath that reads e.g. **"5 WOs ready to
inspect"** in amber, or **"No WOs waiting"** in grey when the queue is clear.

## How do I …

### How do I inspect a work order?

The form appears a piece at a time — you only see the next part after you
finish the one before it.

1. In **Work order**, start typing the number. Pick it from the suggestion
   list, or type it in full and press Enter.
2. The work order card appears: **Part number**, **Quantity**, **Part
   attribute**, **Attribute desc**, and the instruction line Production
   Control wrote for this step. Read that line — it's where they tell you
   anything special about this one.
3. Press **Start Inspection**. The button greys out and reads
   **Inspecting…**, the clock next to it starts running, and the rest of the
   form appears. The clock stops by itself when you save — there is no stop
   button.
4. **Element type** — press **Wye screen**, **Basket**, or **Basket - Flat**.
   Your choice fills in solid, and the right measurement boxes appear:
   Basket gives you **Short length** and **Long length**, Basket - Flat gives
   you **Long length** only, Wye screen gives you neither.
5. Fill in **Overall length** and **Diameter** (and Short/Long if they're
   showing). Type the whole inches then the sixteenth — type `12` then `3`
   and `12-3/16` comes up in the list; pick it.
6. Set **Verified perf**, **Verified mesh**, and **Verified material type**
   from their dropdowns, and pick yourself in **Inspector**.
7. Add anything worth saying in **Notes (max 255)**.
8. Photos: press **Add / take photos**. On a tablet this offers the camera.
   You can add more than one; the line underneath counts them ("2 photos
   added").
9. Press **Pass** or **Fail** — the button you pick fills in, green for Pass
   and red for Fail.
10. Press **Save inspection**. See below for what happens next on a Pass and
    on a Fail.

When the save finishes, the form clears itself back to just the work order
box, ready for the next one.

### How do I finish a work order that passed?

After you press **Save inspection** with **Pass** selected, the app asks:
"Inspection passed. Complete the Inspection step for WO ##### — quantity #?"

- Press **Complete** to finish the step. You'll see "Inspection step complete
  for WO #####", or "Routing complete — WO ##### finished." if Inspection was
  the last step on that work order. Either way the work order drops off your
  list.
- Press **Not yet** if something isn't right. The inspection is still saved,
  but the step is NOT completed and the work order stays on your list. Tell
  Production Control if you meant to complete it.

The whole remaining quantity is completed in one go — the number in the
question is what's left on the step. There's no way to complete part of it
from this app; Production Control does partial quantities from their side.

### How do I record a failed inspection?

Pick **Fail** and press **Save inspection**. The inspection is recorded with
its measurements and photos, and you'll see an orange message telling you to
contact Production Control to reset the routing back to SE. Nothing moves on
its own — **the app does not send the work order anywhere on a Fail**, so
that phone call or message to Production Control is the step that matters.

### How do I re-inspect something that failed?

Just pick the work order again. If the last inspection on it was a Fail, a
red banner reads **"Re-inspection — attempt 2 (prior result: Fail)"** with
the attempt number. Inspect it normally — the app links the new record to the
failed one so the history stays together.

### How do I get a newly ready work order to show up?

Press **Refresh** next to the work order box. You'll see "Work order list
refreshed (N selectable)." This is safe in the middle of an inspection — your
timer keeps running and nothing you've typed is lost.

The **Refresh** button in the left sidebar is a different one: it just
re-counts the ready badge and shows "Badge refreshed." The badge also updates
itself about once a minute.

### How do I look up past inspections?

1. Press **Recent** in the sidebar.
2. Narrow the list with **Date** and **Work order**. Press **All dates** to
   clear the date filter. The count at the top tells you how many records
   you're looking at.
3. Each record shows the work order, part and element type on the first line;
   the measurements and what was verified on the second; and the result,
   inspector and time on the third — green for Pass, red for Fail, with
   "(attempt 2)" on re-inspections.
4. Press **View photos** on a record to see its photos, and the download link
   under a photo to save it.

### How do I print or send an inspection report?

On the **Recent** page, set the **Date** and **Work order** filters to what
you want, then press **Download PDF**. The PDF covers whatever the filters
are showing. **Refresh** reloads the list if someone has saved an inspection
since you opened the page.

## When something looks wrong

- **The work order isn't in the list.** The list only holds work orders whose
  Inspection step is ready or already in progress. Press **Refresh** first.
  If it still isn't there, Production Control hasn't released it to Inspection
  yet — ask them.
- **"Start the inspection timer before saving."** You never pressed **Start
  Inspection**. Press it, then save.
- **"Select a work order first." / "Select an element type." / "Select a
  result (Pass or Fail)." / "Select an inspector."** Something on the form is
  blank — the message names it.
- **"Overall length must look like 12-3/16."** The measurement box has
  something in it the app can't read. Clear it and pick a value from the list
  instead of typing free-hand.
- **Notes won't save.** Notes are capped at 255 characters — shorten them.
- **You picked a different work order part way through.** The timer resets to
  00:00 and the detail fields hide again. That's on purpose: start over on the
  new work order.
- **"Inspection saved (#…), but no routing step was found to complete"** or
  **"…completing the routing step failed"**. Your inspection record is safe,
  but the work order did NOT move. Tell Production Control the work order
  number so they can complete or reset the step.
- **The badge count looks stale.** It refreshes about once a minute; press the
  sidebar **Refresh** to update it now. A Fail doesn't lower the count — the
  work order still needs re-inspecting.

## Who to ask

Chuck Bolton — for the app itself.
Production Control (Dave Whritenour) — for anything about which work orders
are ready, resetting a failed one back to SE, or a step that didn't complete.
