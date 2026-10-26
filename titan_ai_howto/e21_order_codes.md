
# E21 Various Sales and Purchase Order Codes

**Sales Order Header Type Codes:**

1. R – (R)egular
2. D – (D)irect Ship
3. N – retur(N)
4. W – (W)arranty Return
5. F – (F)uture order
6. T – (T)ag and hold
7. C – (C)ancelled
8. S – (S)hip Complete

**Sales Order and Quote Item Status Codes:**

1. Hold (H) = 00
2. Regulatory Hold (R) = 05
3. Entered (E) = 10
4. Committed (C) = 12
5. Allocated (A) = 14
6. Material Received/Shipped (V) = 15 (Means a PO is linked to this line item)
7. Shipped (S) = 16
8. Invoiced (I) = 18
9. Canceled (X) = 90

**Purchase Order Header Types:**

1. R – Regular
2. B – Blanket
3. D – Direct Ship
4. S – Ship Complete
5. N – Return
6. W – Warranty

**Purchase Order Item Status Codes:**

1. PO Entered (E) = 10
2. PO Released to Vendor (R) = 12
3. Material Received from Vendor (V) = 14
4. Closed (C) = 16
5. Vendor Invoice Received (I) = 18
6.  PO Canceled (X) = 20

**Inventory Transaction Type Codes**

1. **ADDINV** - this is a miscellaneous addition to inventory 
2. **INVSUB** - this is a miscellaneous removal from inventory 
3. **SHPMNT** - this represents the shipment of an order out of inventory 
4. **VENDREC** - this represents a receipt in inventory against a purchase order. 
5. **LOCCHG** - this is a location change from one location within a warehouse to another 
6. **PRODCT** - this represents production recorded via Finished Goods Production Recording
7. **ICT** - this represents a transfer of material into the ICT (intra-company transfer, in transit) warehouse
8. **PUTAWY** - this is inventory put-away from a production run INTCOM - this represents an intra-company transfer 
9. **MOVE** - this represents a move of material from one location to another within the same warehouse
10. **DISARM** - this represents raw material that was disassembled in work order production
11. **CSTRET**- this represents inventory from a customer return 
12. **DIRREC** - this represents material that was shipped as part of a direct shipment 
13. **DISAFG** - this represents the disassembly of the finished