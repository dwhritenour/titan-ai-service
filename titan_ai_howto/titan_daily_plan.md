# Titan Daily Plan — How-To Guide
Owner: Dave · App: Titan Daily Plan · Updated: 2026-09-07 (agent proposal + retro added)

## What this app is for
Titan Daily Plan is where Production Control builds **today's Ship Plan**: the list of sales orders that matter most today, measured against how much the assembly crew can actually do. The capacity bar converts orders into **work-inches** (bigger and non-standard-element strainers cost more; check valves and butterfly valves ride free) so the day's plan is compared against real crew capacity, not a guess. A plan is a statement of **importance, not a promise** — being on the plan means "we are working this today," never "this will ship today."

Since September 2026 the app also has an **AI agent** that does two things every weekday morning: it **proposes** a starting plan for today from the flag rankings (so the 08:30 Daily begins with a draft instead of a blank page), and it **reviews yesterday's** published plan against what the records say happened, asking at most three plain questions about the gaps. Nothing the agent does changes the plan on its own — people confirm every line, and Dave confirms every answer.

## What is a work-inch?

**A work-inch is the amount of assembly effort it takes to build one inch of a standard strainer element.** It measures work, not product length.

Not everything we ship costs the same effort. A 30-inch basket takes far longer than a 2-inch one; a non-standard element takes more care per inch than a standard one; and a check valve just gets picked and packed — it uses almost no assembly time at all. Counting orders, pieces, or even inches of product tells you nothing about whether the day fits. Work-inches fixes that by converting everything into one currency: how much of the crew's assembly effort an order consumes, expressed as the equivalent inches of standard element.

- A **standard element** counts its actual length.
- A **non-standard element** (ordered configuration differs from the standard default) counts about 1.6× its length — each inch takes more time.
- **Extra requirements** add their time on top: certain customers' specs, a duplex's second element, mounting a valve.
- **Zero-touch products** (check valves, butterfly valves, temp strainers) count **zero** — they ship without consuming assembly labor.

Capacity works in the same currency: the crew that clocked in this morning × the hours in the day, adjusted for reality, equals how many work-inches the floor can produce today. That's why the bar means something — "Planned 1,400 of 1,986" says the day fits with room to spare, no matter what mix of products is on it.

Two questions people ask, answered honestly. *"Why does that big check-valve order count zero?"* Because it ships without assembly labor; the plan tracks the assembly floor's day, not the shipping dock's. *"Where do the numbers come from?"* From measured build times — about 1.1 minutes per inch for a standard element, 1.78 for non-standard elements — and the capacity arithmetic is printed right under the bar, so the number is never a mystery.

## Who uses it
Production Control builds and publishes the plan (office, and on the meeting whiteboard during the morning Daily with Sales). Sales sees the plan and answers the Sales-side retro questions. The Assembly supervisor takes the published list and decides who builds what — this app never assigns work to people. Dave confirms the agent's readings of retro answers. On the big whiteboard, use the browser's zoom (Ctrl and +) once; it remembers. The boards have no mouse: everything that used to be a hover is now a **tap** (flags, loads, popups).

## A day with the agent, in short
1. **06:30** — the agent reviews yesterday's published plan (the **Retro**) and texts a one-line summary, then proposes today's plan and texts that too.
2. **Before 08:30** — PC opens the app: today's plan already holds the agent's **Proposed** lines; the Retro popup holds yesterday's questions.
3. **08:30 Daily** — PC and Sales confirm, drop, re-tier and add lines; the plan is **published**. Publishing freezes "what we said we'd do."
4. **During the day** — Tara/Kimberly (PC) and Sales answer their retro questions in the app, in their own words. Two minutes each.
5. **Whenever** — Dave confirms the agent's reading of each answer. Three or more of the same confirmed cause in two weeks becomes a proposed rule for Dave to approve or reject.

## How do I …

### How do I read the capacity bar?
The headline says **Planned X of Y work-inches** — X is today's plan so far, Y is today's capacity. The bar fills blue; the number at the fill's edge is the planned total. The faint amber band starts at **85%** (the watch zone) and the red tick is the **cap**. Green text above shows your **headroom**. If the plan goes over capacity, a red segment appears past the cap with **+N over**, so you can see how far over, not just that you're over. The small line underneath shows the arithmetic (crew × hours ÷ efficiency) — the number is never a mystery. A **hatched, lighter bar** means you're looking at a **future day**: capacity is an estimate because that morning's attendance hasn't happened yet.

The agent fills only to **80%** of capacity (the `AGENT_FILL_PCT` parameter). The other 20% is deliberately left open for the day's rush orders. PC can plan past 80% by hand; the agent never does.

### How do I know the data is fresh?
Two small status chips are always on:
- **Attendance ✓ (date)** in green = this morning's clock-in file loaded. **Attendance ⚠** in amber = the file didn't arrive, and capacity is based on an older day's crew.
- **Orders ✓ (time)** in green = the order feed is current. **Orders ⚠ x.x h old** in amber = the feed has been quiet too long.
Green chips mean the board is telling the truth. Amber means plan with care and report it.

### How do I pick which day I'm planning?
The date picker at the top left. It defaults to the next business day. Picking a future day works, but its capacity bar renders hatched (estimate) until that morning arrives.

### How do I find an order to plan?
The **UP NEXT — CANDIDATES** list shows every open order line, **ranked by priority** — the most urgent and most valuable lines at the top, and **gated** lines (ones that can't ship as things stand) parked at the bottom in red. The header tells you how many are showing and how many are gated. Narrow the list with the search box (order #, SKU, or customer), the product dropdown, **Due within horizon** (the next few business days — the window is adjustable in Parameters), **Non-Standard only**, **Unclassified ⚠**, or the **Flag** dropdown: *Plannable only* hides the gated lines when you're building the plan; *Gated only* shows just them for the "what's stuck and why" conversation; *Any A* / *Any B* or a single flag code (say **X03**) narrows to exactly those.

Charge and service lines — TARIFF CHARGE, freight, CODE STAMP, X-RAY, tags, coatings — never appear as candidates. They are sales-order lines, not assembly work. The list of patterns that excludes them lives in a table (`pc_plan_exclusions`), so it grows without a code change; tell Dave when Order Entry invents a new one.

### What do the Flags mean?
Every line carries codes that say why it ranks where it does. **Tap the flag cell** on any row to see its full breakdown (the score and a one-line reason for each flag); **tap the load cell** for the work-inch math. Press **Flag legend** in the filter bar for the live list of every flag and its weight. The four groups:

**X — Eligibility gates** (shown in red with ⛔; these lines can't be planned until the gate clears)
- **X01 Order on hold** — the order or line is on hold in e21.
- **X02 No stock** — a stock item with nothing on hand at Starlite (the reason shows Hub stock if there is any — a transfer candidate).
- **X03 Stock committed to another order** — stock exists, but it's spoken for. This isn't a dead end: it's a reallocation decision for the Daily.
- **X04 No work order** — every open line should have one; if you see this, the import glitched. Tell Production Control.

**A — Urgency & commitments** (the heaviest weights — an urgent line always outranks a merely valuable one)
- **A01 Already late** · **A02 Due today or tomorrow** · **A05 Expedited ship method** (next-day / 2-day air). Coming later: **A03** premium freight / LD exposure, **A04** rush (both proposed by Sales, confirmed by PC), **A06** must-start-today, **A07** carrier cutoff.

**B — Business value** (decides order among equally urgent lines)
- **B02 High dollar** — the order's near-due value is at or above the threshold (currently $15,000; an estimate from last-paid prices until e21 pricing is in the feed). Coming later: **B01** strategic account, **B04** ship-complete one line short, **B05** consolidation, **B06** new customer's first order, **B07** repeatedly bumped.

**C — Informational context** (no weight — they explain the load math)
- **⚠ DEF** — the element type was missing, so the line was charged the conservative Non-Standard rate. **S** — non-standard elements on this line. **Z** — zero-touch product (checks, butterfly valves, temp strainers): it ships, but costs nothing against capacity. **$** — a surcharge applies (SpaceX/Termotran, duplex second element, valve mounting).

**E — Exceptions** — **E01** means an approved exception rule applies to this order (a gate waived, or points added) — approved by Dave through the rules register, never by the agent alone.

The weights are starting values. Production Control tunes them from what actually happens each day, and every change is logged — so if you think two lines are in the wrong order, say so: that's exactly how the ranking gets better.

### How does the agent's morning proposal work?
At **06:30** every weekday the agent builds a proposal for today. It walks the candidates in the same order the pane shows them — ungated, highest score first, then oldest ship-by, then biggest load — and adds lines until the plan reaches **80% of capacity**, on top of anything PC has already planned for the day. Late lines (A01) and lines due today (A02) go in as **Must**; everything else as **Next**. Then it lists up to five more as **Stretch** (the next-best lines that would fit in the remaining room, but are not expected). It never touches gated lines, and it never proposes a single line bigger than half the day's target — those it lists as **split decisions** for PC. Zero-touch products are left off by default (they cost no capacity, so they'd all get proposed).

The result appears on today's plan as lines marked **AGENT PROPOSED ·** with the reason on each ("Must: Late: ship-by 08-17; Expedited: NXTDAY — 33 in, score 160"). A text goes to PC, Sales and Dave with the totals. The **Agent proposal** link under the plan header opens the full story: the narrative the agent wrote (what it chose and why, in terms of the flags and rules, what it left out, what needs a decision) and every proposed line.

### How do I accept or reject a proposed line?
A proposed line is not on the plan until a person says so. On each **AGENT PROPOSED** row, press **✓** to confirm it (it becomes a normal planned line, same tier), **✕** to remove it (give a reason — the agent learns from reasons), or **★** to change its tier. **Accept all proposed** under the header confirms every remaining proposed line at once. Anything still Proposed when you press **Publish** is confirmed automatically — publishing is the agreement.

The remove-and-re-tier reasons matter more than they look. The retro reads them: a line removed *with* a reason is explained and needs no question; a line removed *without* one earns a question the next morning. Please type the reason.

### How do I run the agent by hand?
Press **Run agent** under the plan header (PC only). Use it after a big feed change, or if the 06:30 run was missed. It replaces the agent's earlier still-Proposed lines for that day with a fresh set and keeps everything PC already confirmed. The summary tells you what happened: how many lines, the target, how many gated, how many split decisions, how many zero-touch left off. It refuses a published day (the plan is the agreement by then) and a day with no capacity (a holiday, or nobody on the roster).

### How do I add an order to today's plan?
Press **+** on the candidate row. The whole open balance of that item — all releases combined — moves onto the plan and the capacity bar updates immediately.

### What happens if adding an order goes over capacity?
The order is added anyway (never lost), and a dialog offers three choices: **Snooze to (suggested day)** — the next day with room; **Leave Unplaced** — it stays on today's plan marked red UNPLACED, visibly waiting; or **Keep anyway** — the bar goes red and that's Production Control's call. Every one of these is recorded. Nothing is ever silently dropped.

### What does the ⚑ badge on a plan line mean (like "4 → 2")?
The live order changed after you planned it — part shipped early, or the order was edited. **The plan never changes itself.** The badge shows planned vs. live; click it (or press **↻**) to re-total the line deliberately. The change is logged with before and after. "⚑ no open balance" means it likely shipped — remove the line.

### How do I move or remove a plan line?
**⏰** snoozes the line to a day you pick (it lands on that day's plan). **✕** removes it, with an optional reason — optional to the app, expected by the retro (see above). Removed lines aren't deleted — tick **Show removed** to see them.

### How do I publish the plan?
Press **Publish**. The confirmation shows the planned total, the capacity, and the arithmetic — and if the attendance file is stale, a warning line asks whether to publish anyway. Publishing **stamps** the capacity number onto the plan: that's the number everyone saw, kept forever. It also confirms any leftover proposed lines, records what happened to the agent's proposal (kept, re-tiered, dropped, added by PC), and takes a **snapshot** of every line's flags and score — the record the next morning's retro is measured against. The plan stays editable afterward (real life happens); later changes keep logging, and the retro treats a removal after publish as a variance.

### What is the Retro?
Each weekday morning the agent looks at **yesterday's published plan** and asks, for every planned line, *what does the paperwork say happened?* A line that shipped or had work-order activity is closed with no question. A line removed with a reason is closed, and the reason is recorded as the cause. A line removed with no reason, or a Must/Next line with **no recorded activity at all**, earns a question for PC. On the Sales side, a ship-by date that moved after publish, or a big order that shipped without being on the plan, earns a question for Sales. Stretch lines never earn questions — they were optional.

The agent asks at most **three questions a day** (at least one to Sales when there is a Sales-side variance). The rest are listed as "not asked today" so nothing is hidden — only rationed. A text goes out: "Retro for Tue: 31 of 37 planned lines moved. 2 questions for PC, 1 for Sales."

"No recorded activity" means exactly that — the records show nothing, not that nothing happened. A line can be built without anyone touching the kiosk. That is a legitimate answer ("we built it, the kiosk wasn't used"), and it is recorded as a data-lag finding, not a fault.

### How do I answer a retro question?
Press **Retro** under the plan header. The popup opens on the latest reviewed day (use **◀ prev day** / **next day ▶** to move). Pick your name in **I am:**, read your question — e.g. *"Order 594436 / GASKET ONLY was Must on Tue 09/08 (936 in, late since 08-07) and shows no shipment or work-order activity. Was it started? If not, what stopped it?"* — type what happened in plain words, press **Submit answer**. That's all. Within a couple of minutes the agent writes a one-sentence **reading** of your answer with a suggested cause; you'll see it under your answer marked "awaiting Dave."

Everyone sees every question and every answer, PC's and Sales' alike. That is on purpose: the retro is how the two sides see each other's day, not a private interrogation.

### How does Dave confirm a reading?
The **Awaiting Dave** section lists every answered question with the agent's reading, evidence class and cause. Dave corrects the reading if the agent misread the answer, picks the evidence class (Verified / Probable / Unverified / Disputed / Unknown) and the cause, enters his PIN, and presses **Confirm reading**. Nothing counts as a cause until Dave has done this — that is the rule from the operating cycle: *no verified cause, no permanent rule change.* Questions nobody answers within five business days close themselves as Unknown.

### What are "rule candidates"?
Every Monday the agent counts confirmed causes over the last two weeks. Any cause confirmed **three or more times** becomes a **rule candidate** in the register — a proposal for Dave to approve, reject, or park. The candidate changes nothing by itself. The **Confirmed causes, last 14 days** list at the bottom of the Retro popup shows the counts, with a marker on anything at three.

### What texts will I get?
Two a day on weekdays, to the people tagged for them: the **proposal** text after 06:30 (lines, target, gated, split decisions) and the **retro** text (lines moved, reserve used, how many questions for whom). Every text is logged. If the texts stop, the company-wide SMS switch (the `sms_enabled` row in Global Parameters, shared with the Hub Transfers app) is the first thing to check.

### How do I mark someone absent, or as a trainee?
Press **Mark absent / trainee…** under the capacity bar. Each assembler shows what the morning clock-in feed says; set a person to **Absent**, **Present**, **Trainee** (counts about half), or **HalfDay** to out-vote the feed for that day only. Capacity recalculates when you close the panel.

### How do I change settings or special customers?
Press **Parameters** (Production Control only). Plan parameters: efficiency factor, hours per day, trainee multiplier, the candidate horizon, a manual daily cap override, and the agent's settings — `AGENT_ENABLED` (1/0), `AGENT_FILL_PCT` (80), `AGENT_STRETCH_LINES` (5), `AGENT_RUN_TIME` (06:30), and the retro's `RETRO_MAX_QUESTIONS` (3), `RETRO_MIN_SALES_QUESTIONS` (1), `RETRO_PC_OWNERS` (Tara, Kimberly), `RETRO_UNPLANNED_MIN_INCHES` (50). Special customers: the list (SpaceX, Termotran) whose orders carry extra assembly time — add or adjust without any code change.

### How do I see what happened to a plan?
Press **History**. Every add, snooze, removal, re-total, parameter change, proposal, confirmation and publish is listed with who did it and when.

## When something looks wrong
- **Attendance chip is amber:** the 08:45 clock-in email didn't load — capacity is based on an older day. Tell Dave/check the EasyMorph job; you can still plan, and Publish will warn you.
- **Orders chip is amber:** the order feed is stale — candidate quantities may lag e21. Check the EasyMorph hourly job.
- **An order isn't in the candidates list:** it's already on a plan for today or a future day, or it's a charge/service line (excluded on purpose). Lines on *past* plans that never shipped come back automatically.
- **A line says "no open balance":** it shipped since you planned it. Remove the line.
- **Capacity looks too low:** check the overrides panel (someone marked absent?) and the efficiency factor in Parameters; the arithmetic line under the bar shows exactly what was used.
- **Plan numbers don't match e21 right now:** that's by design — plan lines freeze at the moment you add them, and only update when you deliberately press ↻. Watch for the ⚑ badge.
- **No proposal this morning:** check the Agent proposal link — it says "No agent proposal yet." Either `AGENT_ENABLED` is 0, the day had no capacity (holiday), the day was already published, or the service on the Nexus box wasn't running. Press **Run agent** to produce one now; tell Dave if the 06:30 run is missing two days in a row.
- **The agent proposed something odd:** remove it *with a reason*. That is not a complaint, it is the input the retro and the rules register are built on.
- **The Retro says "No retro for this day yet":** the previous business day's plan was never published, so there was nothing to review. Retros only exist for published days.
- **Retro answers show "Reading pending" for more than a few minutes:** the service on the Nexus box is down or paused. The answer is saved; the reading arrives when the service is back.
- **A retro question is about a charge line or something nobody can act on:** answer it as such ("not real work") — Dave will confirm it as a charge-line cause and the exclusion list gets the pattern.

## Who to ask
Dave Whritenour (app, capacity model, the agent, and the Daily process). Tara and Kimberly (Production Control) own the PC retro answers.
