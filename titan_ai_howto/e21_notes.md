# e21 Notes and Documents — How-To Guide
Owner: Dave · System: e21 (ERP) · Updated: 2026-09-17

## What this guide is for
e21 has SEVERAL kinds of notes and messages, each living in a different place and printing on different paperwork. This guide says where each note type is entered, where it shows up, and what the document type codes mean. Questions like "where do I put a note so it prints on the pick list?" or "what is document type JC?" answer from here.

## Note types — where to enter them and where they appear

### 1. Customer Notes
- Accessed from the **Customer Notes** hot button on the Sales Order, or Options > Customer Notes, or Navigator > Customer Notes
- Does NOT appear on any form or report — internal use only

### 2. Ship To Special Instructions
- Entered at Order Management > Table Maintenance > Customer Information
- Appears at the **bottom of the Pick List**
- Can be shown on the Pick List, Packing List, BOL, or all of them

### 3. Order Notes
- Entered by clicking the **Messages Box** on the Sales Order, or Navigator > Order Notes, or Options > Order Notes
- Applies ONLY to that specific Sales Order
- You choose where and how it appears (A/B, INT, EXT)

### 4. Canned Message
- Set up at Order Management > Table Maintenance > Base Table Maintenance
- Must be tied to the customer via the Customer Master field **OE Msg ID**
- You choose where and how it appears (A/B, INT, EXT)
- Canned Messages can be tied to various objects — see the document type table below

### 5. Customer Note (Customer Master)
- Entered at Customer Master > Navigator > Customer Notes
- You choose where and how it appears (A/B, INT, EXT)
- Separate notes also exist on the **Bill To** and **Ship To** records

**Rule of thumb:** want it internal-only → Customer Notes (type 1). Want it on the pick list for the warehouse → Ship To Special Instructions. Want it on ONE order's paperwork → Order Notes. Want it on EVERY order for a customer → Canned Message.

## External vs internal documents
- **External** (customer-facing): Sales Order Acknowledgment, Packing Slip, Bill of Lading, Invoice, Quote
- **Internal**: Pick List

## e21 Document Type Codes
Codes that identify which object a message/attachment is tied to:

| Code | Meaning |
|------|---------|
| AM | AR Matching |
| BM | Bill of Materials |
| BT | Bill To Address |
| BW | Warehouse-Specific BOM |
| CM | Customer |
| CP | Corporate Parent |
| IN | AR Misc Invoice |
| JC | Job Control Notes |
| PC | Pricing |
| PM | Product |
| PO | Purchase Order |
| PS | Manufacturing |
| QT | Customer Quotes |
| RB | Routing BOM |
| RO | Routing |
| SO | Sales Order |
