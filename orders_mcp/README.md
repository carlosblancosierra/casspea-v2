# Orders MCP server

Read-only [MCP](https://modelcontextprotocol.io) server that lets an assistant
(Claude, or any MCP client) query orders: dates, products, flavours, addresses,
shipping service, tracking. It shows the same data as the orders backend.
It never changes anything. Marking an order shipped, sending tracking emails
and making Royal Mail labels are still done in the backend.

## Tools

| Tool | What it answers |
| --- | --- |
| `get_shipping_queue` | What to post on a day (default today), plus overdue orders and orders with no date. Full packing detail. |
| `get_upcoming_shipments` | Calendar for the next N days: orders, boxes per product, services. |
| `get_pickup_orders` | Store collections between two dates. |
| `get_production_totals` | Chocolates per flavour, random chocolates, boxes per product, pack extras, allergen exclusions, for order ids or a date range. |
| `get_order` | One order in full: address, gift message, lines with flavours, totals, tracking, status history. |
| `list_orders` | Search/filter orders (order date, posting date, status, payment, text). |
| `get_customer_orders` | A customer's history by email. |
| `get_sales_summary` | Revenue, orders, products, services, discount codes, per day/week/month. |
| `list_shipping_options` | Services, prices, delivery days, guaranteed or not. |
| `list_products` | Catalogue with units per box, weight, preorder, fixed posting date, pickup only. |

`shipping_date` is the day the box is **posted**, not the day it is delivered.

## Enable it (HTTP, remote)

1. Generate a secret and set it on the server:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   heroku config:set MCP_API_TOKEN=<secret>     # or the EC2 .env
   ```

   With `MCP_API_TOKEN` unset, `/api/mcp/` answers 503.

2. Connect a client to `https://<api-host>/api/mcp/` (keep the trailing slash).

   **Claude Code**

   ```bash
   claude mcp add --transport http casspea-orders https://<api-host>/api/mcp/ \
     --header "Authorization: Bearer <secret>"
   ```

   **Claude (web/desktop) custom connector**: these can't send a header, so use
   the URL with the token in it: `https://<api-host>/api/mcp/<secret>/`.
   Anyone with that URL can read every order, so treat it like a password.
   If it leaks, change `MCP_API_TOKEN`.

## Run it locally (stdio)

On a machine that can reach the database:

```json
{
  "mcpServers": {
    "casspea-orders": {
      "command": "python",
      "args": ["/path/to/casspea-v2/manage.py", "orders_mcp"]
    }
  }
}
```

## Tests

```bash
python manage.py test orders_mcp --settings=erp.settings_test
```
