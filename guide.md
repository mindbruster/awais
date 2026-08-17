Absolutely. I’ll turn what you provided into a **proper system requirements / functional specification document**, while **not inventing answers** for the business rules you haven’t confirmed yet. Those will be explicitly marked **TBD / Requires Confirmation**.

# Jewellery Manufacturing, Inventory, Sales & Accounting System

## Functional Requirements & Business Process Specification

**Document Status:** Draft
**Purpose:** Define the functional requirements, business workflows, inventory logic, accounting requirements, and manufacturing processes for the jewellery business management system.

---

# 1. System Overview

The proposed system is a complete jewellery business management platform covering:

* Raw material purchasing
* Gold inventory
* Silver inventory
* Diamond and stone inventory
* Jewellery manufacturing
* Maker management
* Stone setter management
* Finished-product inventory
* Loose-material inventory
* Finished-product sales
* Customer management
* Customer ledgers and statements
* Vendor management
* Expenses
* Cash and bank transactions
* Salesmen and brokers
* Sales targets
* Profit and margin reporting
* Gold and silver market rates
* Product marketing/gallery management
* Payment and bill due-date alerts
* Auditing and activity tracking

The system is primarily driven by **physical material movement and corresponding financial/material ledgers**.

The system must be able to answer:

> Where did every gram of gold go?

> Where did every carat of diamond go?

> Which maker or stone setter currently has company material?

> How much material is expected back?

> How much wastage is allowed?

> How much material is actually missing?

> What is the monetary value of the material?

> What is the actual cost and profit of every finished product?

---

# 2. Fundamental Units

The system has two primary measurement units.

## 2.1 Gold

Gold is always measured in:

**Grams**

Gold purchased as raw material is always:

**24K pure gold**

Gold returned from manufacturing may have different purity levels, such as:

* 24K
* 21K
* 18K
* 14K
* Other configured purity levels

---

## 2.2 Diamonds / Stones

Diamonds can be recorded in:

* Carats
* Grams

The confirmed conversion is:

**1 gram of diamond = 5 carats**

Therefore:

**1 carat = 0.2 grams**

For example:

30 carats ÷ 5 = 6 grams

The system should internally be capable of converting between grams and carats, while the finished-product inventory should primarily display diamond weight in **carats**.

---

# 3. Raw Material Inventory

The initial stock consists of three major categories.

## 3.1 Gold

Gold is purchased as pure 24K gold.

Example:

```text
Material: Pure Gold
Purity: 24K
Weight: 1,000 grams
```

The inventory must maintain:

* Quantity/weight
* Purity
* Purchase cost
* Purchase date
* Supplier/vendor
* Transaction reference
* Current stock
* Historical movements

---

## 3.2 Silver

Silver is purchased in pure form with:

**999 purity**

Silver must have its own inventory separate from gold.

The exact purity/conversion rules used during manufacturing require confirmation.

---

## 3.3 Stones / Diamonds

The system must support multiple stone types.

The business must be able to define stone names itself.

Examples:

```text
Diamond
Ruby
Emerald
Sapphire
Moissanite
Other configured stones
```

Each stone type must have its own inventory.

For diamonds, inventory should support:

* Carat weight
* Gram equivalent
* Purchase cost
* Supplier
* Purchase date
* Stock/lot
* Material movement
* Current quantity

---

# 4. Inventory Principle

The system must maintain **stock movement history**.

Inventory should not simply be overwritten.

Every movement should create a transaction.

Examples:

```text
Purchase → Stock In

Gold → Maker → Stock Out

Maker → Company → Stock In

Diamond → Stone Setter → Stock Out

Stone Setter → Company → Stock In

Finished Product → Customer → Stock Out
```

This allows complete traceability and auditing.

---

# 5. Maker Manufacturing Process

The maker is responsible for converting pure/raw gold into jewellery.

## 5.1 Gold Issued to Maker

The company may issue pure 24K gold to a maker.

Example:

```text
Gold issued:
100.000 grams
Purity:
24K
```

The system must create:

* Gold stock-out transaction
* Maker material ledger entry
* Maker transaction reference
* Date/time
* Responsible employee/user

---

# 6. Maker Agreement Types

The maker's manufacturing agreement can operate using different methods.

The confirmed options are:

### Option 1 — Gold Wastage

Maker settlement is based on a gold wastage calculation.

### Option 2 — Price Per Gram

Maker charges a monetary amount based on the manufactured weight.

The maker's agreement must therefore contain a configurable **calculation type**.

Example:

```text
Maker Agreement Type:
Wastage
```

or:

```text
Maker Agreement Type:
Price Per Gram
```

The exact price-per-gram calculation requires further confirmation.

---

# 7. Maker Wastage Calculation

The provided business rule uses **ratti**.

Maker wastage may be between:

**1 and 24 ratti**

The provided formula is:

```text
Maker Wastage
=
Received Product Weight ÷ 96 × Wastage Ratti
```

### Example

If:

```text
Returned product weight = 100g
Wastage = 4 ratti
```

Then:

```text
100 ÷ 96 × 4
=
4.1667g
```

The exact interpretation of this formula and whether 96 is always the fixed divisor must be confirmed before implementation.

---

# 8. Adjusted Maker Weight

The provided process indicates that the calculated maker wastage is added to the returned product weight.

Conceptually:

```text
Adjusted Weight
=
Returned Weight
+
Calculated Maker Wastage
```

This adjusted weight is then used for the pure-gold-equivalent calculation.

This rule requires final business confirmation before implementation.

---

# 9. Purity Conversion

When the maker returns jewellery in a purity lower than 24K, its weight must be converted to a 24K/pure-gold equivalent.

The provided formula is:

```text
Pure Gold Equivalent
=
Adjusted Weight × Purity ÷ 24
```

### Example

For:

```text
Adjusted Weight = 100g
Purity = 18K
```

Calculation:

```text
100 × 18 ÷ 24
=
75g
```

Therefore:

**100g of 18K jewellery = 75g of pure-gold equivalent**

This pure-gold equivalent is used for the maker's material ledger.

---

# 10. Maker Gold Ledger

Every maker must have a material ledger.

The ledger should track:

| Field                | Description                      |
| -------------------- | -------------------------------- |
| Transaction ID       | Unique transaction               |
| Maker                | Maker involved                   |
| Gold Issued          | Pure gold given                  |
| Product Returned     | Product received                 |
| Returned Weight      | Physical returned weight         |
| Returned Purity      | 18K, 21K, etc.                   |
| Wastage              | Calculated maker wastage         |
| Adjusted Weight      | Weight after wastage calculation |
| Pure Gold Equivalent | Converted 24K equivalent         |
| Gold Balance         | Remaining material obligation    |
| Cash Charges         | Applicable manufacturing charges |
| Due Date             | If applicable                    |
| Status               | Open / Settled / Pending         |

The system should clearly show the amount of gold that is:

* Given to maker
* Received back
* Consumed
* Allowed as wastage
* Still receivable
* Settled

---

# 11. Maker — No Gold Given Upfront

The system must support cases where the company does **not** provide pure gold to the maker before manufacturing.

In such cases, the maker can manufacture the jewellery first, while the company creates a future gold obligation.

Example:

```text
Maker:
ABC Maker

Gold given initially:
0g

Product received:
XXg

Gold obligation:
XXg pure-gold equivalent

Due date:
Configured date
```

The obligation must remain visible in the maker ledger until it is settled.

### Important Business Rule

The exact calculation and timing of this obligation require confirmation.

---

# 12. Finished Product Serial Number

When a product is received from the maker, the system must assign a unique product serial number.

The system may generate this automatically.

Example:

```text
JWL-000001
JWL-000002
JWL-000003
```

The serial number must remain associated with the product throughout its lifecycle.

The product history should therefore be traceable:

```text
Raw Material
    ↓
Maker
    ↓
Finished Product
    ↓
Stone Setter
    ↓
Final Product
    ↓
Inventory
    ↓
Customer Sale
```

---

# 13. Product Identification

Each finished jewellery product should contain at minimum:

* Product ID
* Product serial number
* Product code
* Product name
* Product image
* Gold weight
* Gold purity
* Diamond weight
* Diamond carats
* Stone details
* Manufacturing history
* Maker
* Stone setter
* Product cost
* Selling price
* Product status

---

# 14. Stone Setter Process

After receiving the jewellery from the maker, the product may be sent to a stone setter.

The company also issues diamonds/stones from its inventory.

The system must record both:

1. Jewellery/product given to the stone setter
2. Stones given to the stone setter

---

# 15. Diamond Weight Conversion for Stone Setter

Suppose:

```text
Jewellery weight = 100g
Diamond quantity = 30 carats
```

Using:

```text
1g diamond = 5 carats
```

the diamond weight is:

```text
30 ÷ 5
=
6g
```

Therefore:

```text
Gold/Product weight = 100g
Diamond equivalent = 6g
--------------------------------
Total weight given = 106g
```

The system must automatically perform this calculation.

---

# 16. Multiple Diamond Stock Sources

The required diamond quantity may come from multiple inventory records/lots.

Example:

```text
Diamond Stock A = 5 CT
Diamond Stock B = 10 CT
Diamond Stock C = 8 CT
Diamond Stock D = 7 CT

Total = 30 CT
```

The system must record each stock source used.

This is necessary for:

* Inventory accuracy
* Cost calculation
* Traceability
* Auditing

---

# 17. Stone Setter Wastage

The stone setter agreement includes a gold wastage rule.

Example:

```text
Wastage:
0.400g per 100 pieces
```

If 350 pieces/stones are set:

```text
0.400 ÷ 100 × 350
=
1.400g
```

Therefore:

**Allowed wastage = 1.400g**

The system must calculate this automatically.

---

# 18. Stone Setter Configuration

The stone-setting agreement must support editable values.

At minimum:

### Rule 1 — Gold Wastage

```text
Wastage per:
100 pieces/stones

Wastage:
0.400g
```

### Rule 2 — Stone Setting Charge

Example:

```text
Charge per stone:
Rs. 5
```

or:

```text
Charge per stone:
Rs. 10
```

The values must be editable per transaction/agreement where required.

---

# 19. Stone Setting Charges

If:

```text
Number of stones = 350
Charge per stone = Rs. 5
```

Then:

```text
350 × 5
=
Rs. 1,750
```

The system should record this as the stone-setting manufacturing charge.

---

# 20. Stone Setter Return Process

The stone setter returns the jewellery after setting the stones.

The system records the actual returned gross weight.

Example:

```text
Weight given:
106g

Weight received:
102g
```

The system calculates:

```text
Weight difference:
106 - 102
=
4g
```

---

# 21. Stone Setter Weight Reconciliation

The system compares:

**Expected/issued weight**

against:

**Actual returned weight**

Example:

```text
Total weight given:       106.000g
Total weight received:    102.000g
----------------------------------
Total difference:           4.000g
```

Allowed wastage:

```text
1.400g
```

Excess shortage:

```text
4.000 - 1.400
=
2.600g
```

Therefore:

**2.600g becomes receivable from the stone setter**, according to the provided business example.

The system should clearly display this instead of hiding the calculation.

---

# 22. Stone Setter Ledger

Each stone setter should have a complete material ledger.

Example:

| Description           |   Weight |
| --------------------- | -------: |
| Product given         | 100.000g |
| Diamond weight        |   6.000g |
| Total material given  | 106.000g |
| Gross weight received | 102.000g |
| Total difference      |   4.000g |
| Allowed wastage       |   1.400g |
| Excess shortage       |   2.600g |

The ledger should additionally record:

* Number of stones
* Stone types
* Diamond stock sources
* Stone-setting charges
* Date sent
* Date returned
* Due date
* Settlement status
* Responsible employee

---

# 23. Gross and Net Weight

The system must distinguish between:

### Gross Weight

The complete physical returned weight.

### Net Weight

The business-defined weight after excluding the applicable stone/diamond weight.

Based on the provided example:

```text
Gross returned weight = 102g
Diamond weight = 6g

Net weight =
102 - 6
=
96g
```

However, the exact definition of "net weight" must be confirmed before implementation because jewellery businesses may use different definitions of gross, net, stone weight, and gold weight.

---

# 24. Finished Product Stock

After the manufacturing and stone-setting process, the product enters finished-product stock.

The stock record should show:

```text
Product ID
Product Code
Product Name
Image
Gold Purity
Gold Weight
Diamond Weight
Diamond CT
Stone Details
Manufacturing Cost
Total Cost
Selling Price
Current Status
```

Diamond weight should be displayed in:

**Carats (CT)**

The system may also retain its gram equivalent internally.

---

# 25. Finished Product Invoice

The system must support a finished-product invoice.

Required fields:

| Field         |
| ------------- |
| SR            |
| Product Code  |
| Product Name  |
| Gold Weight   |
| Discount      |
| Diamond CT    |
| Diamond Price |
| Amount        |
| Product Image |

The product should be selected from finished-product inventory.

The invoice should therefore be connected directly to the product's serial number/product ID.

---

# 26. Loose Material Invoice

The system must support a separate invoice type for loose materials.

Required fields:

| Field         |
| ------------- |
| SR            |
| Product Code  |
| Product Name  |
| Diamond CT    |
| Diamond Price |
| Discount      |
| Amount        |

This invoice is intended for selling diamonds/stones or other loose materials rather than finished jewellery.

---

# 27. Customer Management

The customer module must contain:

* Customer profile
* Contact details
* Customer code
* Sales history
* Invoices
* Payments
* Outstanding balances
* Customer ledger
* Customer statements
* Sales targets
* Profitability

---

# 28. Customer Ledger

Every customer should have a complete ledger.

It should show:

```text
Date
Transaction
Invoice
Debit
Credit
Payment
Balance
```

The ledger must allow the business to determine the customer's current outstanding amount.

---

# 29. Customer Statements

The system must generate customer statements showing the complete financial relationship between the company and the customer.

Statements should include:

* Opening balance
* Sales
* Payments
* Adjustments
* Returns
* Closing balance

---

# 30. Customer Sales Ranking

Customers should be ranked from:

**Highest spending → Lowest spending**

The system should be able to generate reports such as:

```text
Customer A     Rs. X
Customer B     Rs. Y
Customer C     Rs. Z
```

The ranking period should be configurable.

---

# 31. Customer Profitability

The system must calculate profitability by customer.

Example:

```text
Customer Revenue
-
Product/Material Cost
-
Applicable Costs
=
Customer Profit
```

The system should display:

* Total sales
* Total cost
* Gross profit
* Profit margin
* Number of transactions

The exact costing methodology is dependent on the final profit setup.

---

# 32. Expense Management

The system must support business expenses.

Expenses should support different payment methods, including:

* Cash
* Bank
* Other configured receiving/payment accounts

Each expense should contain:

* Date
* Expense category
* Description
* Amount
* Payment method
* Account
* Responsible user
* Supporting document/bill
* Notes

---

# 33. Daily Cash Report

The system should produce a daily cash-flow report.

Conceptually:

```text
Opening Cash
+
Cash Received
-
Cash Expenses
-
Cash Payments
=
Closing Cash
```

The report should provide a detailed breakdown of all cash movements.

---

# 34. Bank Transactions

The business should be able to manually configure bank receiving/payment accounts.

The system should support:

* Bank account creation
* Bank receipts
* Bank payments
* Transfers
* Account-wise balances
* Transaction history

---

# 35. Vendor Management

The vendor module must contain:

* Vendor profile
* Vendor contact details
* Bills
* Purchases
* Payments
* Outstanding balances
* Due dates
* Payment history
* New vendor creation

The system must maintain a complete financial/material relationship with every vendor.

---

# 36. Vendor Due Dates

Vendor bills must support due dates.

The system should identify:

* Upcoming bills
* Due today
* Overdue bills
* Paid bills
* Partially paid bills

---

# 37. Gold and Silver Market Rates

The system should have a dedicated **Market Rates** tab.

It should display:

* Current gold rate
* Current silver rate

The live rate functionality should be separate from the normal inventory interface.

Historical transactions must retain their original transaction/cost information rather than being blindly overwritten by future market-rate changes.

The exact treatment of market rates in profit calculations requires confirmation.

---

# 38. Salesman / Broker Management

The system must support salesmen and brokers.

Each salesman/broker should have:

* Profile
* Assigned invoices
* Sales
* Collections
* Targets
* Performance
* Reports
* Customer relationships
* Bills assigned

The system should allow management to determine how much business each salesperson/broker generates.

---

# 39. Company Sales Targets

The system should support company-wide sales targets.

Targets may be:

* Monthly
* Annual
* Custom date range

Example:

```text
Target:
Rs. 50,000,000

Period:
January 2027

Actual:
Rs. XX,XXX,XXX

Achievement:
XX%
```

---

# 40. Customer Sales Targets

Targets can also be assigned to individual customers.

Example:

```text
Customer:
ABC Jewellers

Target:
Rs. 5,000,000

Period:
January 2027
```

The system should track:

```text
Target
Actual Sales
Remaining Target
Achievement %
```

---

# 41. Profit Calculation System

The system must support **two separate profit setups**.

The business has identified:

### Setup 1 — Gold

Gold profitability depends on:

* Gold capital/cost
* Gold quantity
* Gold purity
* Gold purchase cost
* Gold rate
* Gold market-rate changes

### Setup 2 — Raw Materials / Diamonds

Diamond and raw-material profitability depends on:

* Purchase cost
* Inventory cost
* Quantity
* Selling price
* Discounts
* Applicable manufacturing costs

The exact formulas for both profit systems are **TBD** and must be finalized with the business before implementation.

---

# 42. Gold Capital and Costing

The system must track gold as a valuable inventory asset.

Gold records should contain:

```text
Quantity
Purity
Purchase cost
Purchase rate
Current market rate
Pure-gold equivalent
Material movements
```

The system must distinguish between:

**Historical acquisition cost**

and

**Current market value**

where required.

---

# 43. Product Marketing Gallery

The system must provide a dedicated product-picture section.

Products should be displayed in a grid.

Example:

```text
┌──────────┐ ┌──────────┐ ┌──────────┐
│ Product  │ │ Product  │ │ Product  │
│ Image    │ │ Image    │ │ Image    │
│ JWL-001  │ │ JWL-002  │ │ JWL-003  │
└──────────┘ └──────────┘ └──────────┘
```

Clicking a product should open its details.

Details should include:

* Product ID
* Product image
* Gold amount
* Gold purity
* Diamond amount
* Diamond CT
* Stone details
* Product price
* Other marketing information

---

# 44. Due-Date Alerts

The system should generate alerts for:

* Customer payments
* Vendor bills
* Maker settlements
* Stone setter settlements
* Other business bills

Possible statuses:

```text
Upcoming
Due Today
Overdue
Paid
Partially Paid
```

Alerts may appear in the dashboard and notification area.

---

# 45. Audit System

The system must contain a complete audit trail.

For important operations, the system should record:

* User
* Date/time
* Action
* Record affected
* Previous value
* New value
* Transaction reference

Auditing should cover:

* Inventory
* Gold
* Silver
* Diamonds
* Makers
* Stone setters
* Products
* Customers
* Vendors
* Invoices
* Payments
* Expenses
* Manual adjustments
* Rate changes
* Ledger modifications

---

# 46. Dashboard

The main dashboard should provide an overview of the business.

Potential dashboard information:

### Inventory

```text
Gold Stock
Silver Stock
Diamond Stock
Finished Products
Loose Materials
```

### Financial

```text
Today's Sales
Today's Cash
Outstanding Customer Receivables
Vendor Payables
Expenses
Profit
```

### Manufacturing

```text
Gold with Makers
Products with Makers
Products with Stone Setters
Diamond stock issued to Setters
Pending Settlements
```

### Alerts

```text
Due Payments
Overdue Bills
Maker Obligations
Stone Setter Receivables
```

---

# 47. Core Manufacturing Lifecycle

The complete manufacturing lifecycle should follow this general flow:

```text
RAW MATERIAL PURCHASE
        │
        ├── 24K GOLD
        ├── 999 SILVER
        └── DIAMONDS / STONES
                │
                ↓
          RAW MATERIAL STOCK
                │
                ↓
              MAKER
                │
                ↓
        JEWELLERY RECEIVED
                │
                ↓
        PRODUCT SERIAL NUMBER
                │
                ↓
         STONE SETTER
          ↑          ↑
          │          │
      PRODUCT      STONES
          │          │
          └────┬─────┘
               ↓
        WEIGHT RECONCILIATION
               │
               ↓
         FINAL PRODUCT
               │
               ↓
      FINISHED PRODUCT STOCK
               │
          ┌────┴────┐
          ↓         ↓
        SALE      GALLERY
          │
          ↓
       CUSTOMER
          │
          ↓
   CUSTOMER LEDGER
```

---

# 48. Material Traceability

Every material movement should be traceable.

For example, a final product should be able to show:

```text
Product:
JWL-000123

Gold:
100g from Gold Stock #G-001

Diamond:
10 CT from Stock #D-011
15 CT from Stock #D-024
5 CT from Stock #D-031

Maker:
Maker ABC

Stone Setter:
Setter XYZ
```

This allows the business to trace the origin and movement of every material.

---

# 49. Important Business Rule: No Silent Stock Changes

The system should never allow important inventory values to change without a transaction.

For example:

```text
100g gold
```

should not simply become:

```text
95g gold
```

without a recorded reason.

Instead:

```text
100g opening stock
-
5g issued to maker
=
95g remaining
```

Every stock change must have a source transaction.

---

# 50. Important Business Rule: Historical Records

Historical transactions should remain intact.

For example, if gold rate changes tomorrow, an old purchase should retain:

```text
Original purchase date
Original purchase quantity
Original purchase rate
Original purchase cost
```

Current market rates should be stored separately.

This is especially important for audit and profitability reporting.

---

# 51. Required Reporting

The system should eventually support reports including:

## Inventory Reports

* Gold stock
* Silver stock
* Diamond stock
* Stone stock
* Finished products
* Loose materials
* Stock movement

## Manufacturing Reports

* Gold with makers
* Products with makers
* Products with stone setters
* Stone-setting wastage
* Maker wastage
* Material shortages
* Material receivables

## Sales Reports

* Daily sales
* Monthly sales
* Annual sales
* Customer sales
* Salesman sales
* Broker sales
* Product sales

## Financial Reports

* Daily cash report
* Bank report
* Expenses
* Customer receivables
* Vendor payables
* Profit
* Profit margin
* Cash flow

## Customer Reports

* Top customers
* Lowest-spending customers
* Customer profitability
* Customer statements
* Customer outstanding balances

## Audit Reports

* User activity
* Stock adjustments
* Invoice modifications
* Financial modifications
* Inventory history

---

# 52. Business Rules Requiring Confirmation

The following items must **not be implemented based on assumptions**.

## Maker

1. Exact ratti wastage formula.
2. Confirmation that 96 is always the divisor.
3. Confirmation that calculated wastage is added to returned weight.
4. Exact settlement formula for maker gold.
5. Exact price-per-gram maker calculation.
6. Exact treatment of gold when no gold is initially provided.
7. Exact due-date/settlement mechanism.

## Silver

8. Exact purity system for silver manufacturing.
9. Whether silver uses the same karat calculation as gold.

## Stone Setter

10. Exact meaning of "piece" in the 100-piece wastage calculation.
11. Whether wastage is based on number of stones or another quantity.
12. Whether excess shortage is settled in physical gold, cash, or either.
13. Exact definition of net weight.

## Diamonds / Stones

14. Whether the 1g = 5CT conversion applies only to diamonds or every stone.
15. Diamond costing method when multiple stock lots are consumed.
16. FIFO vs weighted average vs exact-lot costing.

## Profit

17. Exact formula for Profit Setup #1.
18. Exact formula for Profit Setup #2.
19. Whether profit uses historical gold cost, current market rate, or both.
20. Treatment of manufacturing charges in product cost.

## Market Rates

21. Gold rate source/API.
22. Silver rate source/API.
23. Whether rates are informational only or participate directly in valuation/profit calculations.

---

# 53. Recommended Core Modules

The final application should be divided into the following major modules:

```text
1. Dashboard

2. Inventory
   ├── Gold
   ├── Silver
   ├── Diamonds
   ├── Stones
   ├── Finished Products
   └── Loose Materials

3. Manufacturing
   ├── Makers
   ├── Maker Transactions
   ├── Stone Setters
   └── Stone Setting Transactions

4. Products
   ├── Product Management
   ├── Product Serial Numbers
   ├── Product Costing
   └── Product Gallery

5. Sales
   ├── Finished Product Invoices
   ├── Loose Material Invoices
   ├── Salesmen
   └── Brokers

6. Customers
   ├── Customer Management
   ├── Customer Ledger
   ├── Customer Statements
   ├── Customer Targets
   └── Customer Profitability

7. Vendors
   ├── Vendor Management
   ├── Vendor Bills
   ├── Vendor Payments
   └── Vendor Ledger

8. Finance
   ├── Cash
   ├── Banks
   ├── Expenses
   ├── Receipts
   ├── Payments
   └── Cash Flow

9. Targets
   ├── Company Targets
   └── Customer Targets

10. Market Rates
    ├── Gold
    └── Silver

11. Reports

12. Alerts

13. Audit Logs

14. System Settings
```

---

# 54. Guiding Principle

The most important architectural principle for this system is:

> **Every physical material movement and every financial movement must create a traceable transaction.**

The system should never rely only on manually changing stock balances.

For gold:

```text
Gold Purchased
        ↓
Gold Stock
        ↓
Gold Given to Maker
        ↓
Gold/Product Received
        ↓
Pure Gold Equivalent
        ↓
Maker Ledger
```

For diamonds:

```text
Diamond Purchased
        ↓
Diamond Stock
        ↓
Diamond Issued to Setter
        ↓
Diamond Used in Product
        ↓
Finished Product
        ↓
Product Sale
```

For cash:

```text
Customer Payment
        ↓
Cash/Bank
        ↓
Financial Ledger
        ↓
Customer Balance
```

This transaction-driven approach is essential for maintaining accurate inventory, accounting, reporting, and auditing.

---

# 55. Current Specification Status

The overall business workflow and required modules are now documented.

However, the system should **not yet have final formulas implemented** for the areas explicitly marked as requiring confirmation.

The next stage should be to finalize:

1. Maker gold formulas
2. Maker settlement rules
3. Silver purity rules
4. Stone-setter wastage rules
5. Net/gross weight definitions
6. Diamond stock costing
7. Gold costing
8. The two profit calculation systems
9. No-gold-upfront maker workflow
10. Market-rate treatment

Once these rules are confirmed, they can be converted into **exact mathematical formulas, database rules, transaction flows, and test cases**.
