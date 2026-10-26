# e21 Codes Reference (Orders, POs, Inventory, SKUs) — How-To Guide
Owner: Dave · System: e21 (ERP) · Updated: 2026-09-17

## What this guide is for
Decoding e21's letter and number codes: sales-order types and statuses, purchase-order types and statuses, inventory transaction types, and SKU item types. Questions like "what does an order status of F mean?", "what is item status 16?", or "what does VENDREC mean?" answer from here.

**Also in the database:** the live, authoritative code list is `dbo.e21_code_lookup` (filter by `code_set`, e.g. INV_TRANS_TYPE) — query it when a code isn't listed here or when exact labels matter.

## Sales Order Header Type Codes
One letter on the order header, describing the KIND of order:

- **R** – Regular
- **D** – Direct Ship
- **N** – Return
- **W** – Warranty Return
- **F** – Future order
- **T** – Tag and hold
- **C** – Cancelled
- **S** – Ship Complete

## Sales Order and Quote ITEM Status Codes
Each line item carries a numeric status (with a letter shorthand). Lines move UP this ladder as they progress:

- **00 (H)** – Hold
- **05 (R)** – Regulatory Hold
- **10 (E)** – Entered
- **12 (C)** – Committed
- **14 (A)** – Allocated
- **15 (V)** – Material Received/Shipped — means a PO is linked to this line item
- **16 (S)** – Shipped
- **18 (I)** – Invoiced
- **90 (X)** – Canceled

Note: un-shipped lines can sit at status 10 indefinitely and re-release later — a status-10 line is not necessarily stuck.

## Purchase Order Header Types
- **R** – Regular
- **B** – Blanket
- **D** – Direct Ship
- **S** – Ship Complete
- **N** – Return
- **W** – Warranty

## Purchase Order ITEM Status Codes
- **10 (E)** – PO Entered
- **12 (R)** – PO Released to Vendor
- **14 (V)** – Material Received from Vendor
- **16 (C)** – Closed
- **18 (I)** – Vendor Invoice Received
- **20 (X)** – PO Canceled

## Inventory Transaction Type Codes
What each transaction code in e21 inventory history means:

- **ADDINV** – miscellaneous addition to inventory
- **INVSUB** – miscellaneous removal from inventory
- **SHPMNT** – shipment of an order out of inventory
- **VENDREC** – receipt into inventory against a purchase order
- **LOCCHG** – location change within a warehouse
- **PRODCT** – production recorded via Finished Goods Production Recording
- **ICT** – transfer from ocean warehouse to Titan warehouse
- **PUTAWY** – inventory put-away from a production run (INTCOM)
- **MOVE** – move of material between locations within the same warehouse
- **DISARM** – raw material disassembled in work-order production
- **CSTRET** – inventory from a customer return
- **DIRREC** – material shipped as part of a direct shipment
- **DISAFG** – disassembly of finished goods
- **REGRDE** – regrade of the product
- **INTCOM** – transfer of material into the ICT (intra-company transfer, in-transit) warehouse

## e21 SKU Item Types
The item type determines how the system processes the item. Most common:

- **S** – Stock, Substitute OK
- **N** – Non-Stock (not in Product Master)
- **D** – Direct Ship
- **U** – Stock, No Substitute
- **H** – Stock, Handle as Non-stock — history is NOT recorded and product codes are not validated against product maintenance
- **F** – Found Item — the system will not use this sale to forecast future ordering
- **X** – Surplus Item — history is not recorded and sales are not used in forecasting future purchases
