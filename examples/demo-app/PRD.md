# Brewly — Product Requirements

Brewly is a small online ordering service for a specialty coffee shop. Customers
browse the menu, place an order for a single item, and pay at checkout.

## Requirements

**R1 — Menu.** The service exposes the shop menu. Each menu item has a name, a
price in USD, and a current stock count. The launch menu is fixed: Espresso
($3.00), Latte ($4.50), Cold Brew ($4.00), Matcha Latte ($5.00), each starting
with 10 units in stock.

**R2 — Place order.** A customer can order one menu item in a chosen quantity
(1–100). A successful order returns an order id, the quantity, and the total
price (unit price × quantity). Placing an order immediately reserves stock:
the item's stock count decreases by the ordered quantity.

**R3 — Stock validation.** If the requested quantity exceeds the item's current
stock, the order is rejected with a conflict error ("insufficient stock") and
stock is not changed.

**R4 — Bulk discount.** Orders of 4 or more units receive a 10% discount,
applied at checkout time to the order total, rounded to cents.

**R5 — Checkout.** A customer pays for a pending order at checkout. Checkout
marks the order as `paid` and returns the final total (with any discount
applied). Checking out an already-paid order is rejected with a conflict error.

**R6 — Order lookup.** An order can be retrieved by id at any time, showing its
quantity, total, and status (`pending` or `paid`). Unknown order ids return
not-found.

## Interfaces

- REST API under `/api` (OpenAPI at `/openapi.json`).
- Web storefront at `/`: menu grid, order form, order confirmation status.

## Out of scope

Accounts, payments processing, multi-item carts, inventory restocking.
