## Product custom options & cart integration

This document describes how products expose flexible custom options and how cart items reference them.

### Backend changes

- **Product model**
  - Added `custom_options = models.JSONField(default=list, blank=True, help_text="Flexible list of custom options for this product")`.
  - Purpose: allow each product to define a list of arbitrary, JSON‑serializable option objects.
  - Typical structure for each option:
    - `key` (string, unique per product): stable identifier used by the frontend and cart.
    - `label` (string): human‑readable label to display.
    - Optional fields like `description`, `price_delta`, or any other product‑specific metadata.

- **Product serializer**
  - `ProductSerializer` now includes the `custom_options` field in its `fields` list, so every product API response exposes the full list of options.

- **CartItem model**
  - Added
    - `selected_custom_option_key = models.CharField(max_length=255, null=True, blank=True, help_text="Identifier of the selected custom option from the product")`.
  - Purpose: store which option (by `key`) was selected for that particular cart line item.

- **Cart serializers**
  - `CartItemSerializer` (read):
    - Exposes `selected_custom_option_key` so the frontend can see which option was chosen for each cart line.
  - `CartItemCreateSerializer` (write):
    - Accepts optional `selected_custom_option_key`.
    - Validation:
      - Reads `product.custom_options` and collects all `key` values from option objects.
      - If `selected_custom_option_key` is provided, it must be one of these keys.
      - If product has no valid option keys or the provided key is not found, the serializer raises:
        - `{"selected_custom_option_key": "Selected option is not valid for this product."}`

### Data shape examples

Example `custom_options` on a product:

```json
[
  {
    "key": "standard_wrap",
    "label": "Standard wrapping",
    "description": "Classic wrapping at no extra cost",
    "price_delta": "0.00"
  },
  {
    "key": "premium_wrap",
    "label": "Premium wrapping",
    "description": "Luxury paper and ribbon",
    "price_delta": "3.00"
  }
]
```

Example cart item response:

```json
{
  "id": 1,
  "quantity": 1,
  "product": {
    "...": "...",
    "custom_options": [
      { "key": "standard_wrap", "label": "Standard wrapping" },
      { "key": "premium_wrap", "label": "Premium wrapping" }
    ]
  },
  "selected_custom_option_key": "premium_wrap",
  "base_price": "25.00",
  "discounted_price": "25.00",
  "savings": "0.00"
}
```

### Frontend usage

#### Reading options for a product

- From any endpoint using `ProductSerializer`, read `product.custom_options`.
- If the array is empty or missing:
  - Hide the options UI for that product.
- If the array has entries:
  - Render a selector (dropdown, radio buttons, etc.) where:
    - Each option’s `value` is the `key`.
    - Each option’s label is `label` (and optionally `description`).

#### Sending the selected option when adding to cart

- POST body for creating a cart item (simplified):

```json
{
  "product": 123,
  "quantity": 1,
  "selected_custom_option_key": "premium_wrap"
}
```

- Notes:
  - `selected_custom_option_key` is optional.
  - Only send it when the user has actually chosen a specific option.
  - If the key does not exist in `product.custom_options[].key`, the API responds with a 400 error and a `selected_custom_option_key` validation message.

#### Showing the selected option in the cart

- For each cart item:
  - Use `item.selected_custom_option_key` together with `item.product.custom_options` to:
    - Look up the matching option object by `key`.
    - Display the human‑readable `label` (and any pricing/description metadata).

### Frontend types (TypeScript)

Ensure `CartItem` includes the selected option key so it appears on cart and order responses:

```ts
// In your CartItem interface (e.g. ./carts), add:
export interface CartItem {
  id: number;
  quantity: number;
  product: { /* ... */; custom_options?: Array<{ key: string; label: string }> };
  selected_custom_option_key?: string | null;  // add this
  // ... base_price, discounted_price, savings, box_customization, pack_customization, etc.
}
```

Then `Order.checkout_session.cart.items` (which is `CartItem[]`) will correctly type the selected option:

```ts
import { Address } from "./addresses";
import { CartItem } from "./carts";

export interface Order {
  order_id: string;
  shipping_order_id?: string;
  tracking_number?: string;
  status: string;
  created: string;
  updated: string;
  shipped?: string;
  delivered?: string;
  checkout_session: {
    payment_status: string;
    shipping_address: Address;
    shipping_option: {
      id: number;
      name: string;
      price: string;
    };
    total_with_shipping: number;
    cart: {
      items: CartItem[];  // each item has selected_custom_option_key
      discount?: string | null;
      gift_message?: string | null;
      shipping_date?: string | null;
      discounted_total: string;
      pickup_date?: string | null;
      pickup_time?: string | null;
    };
  };
  past_orders?: string[];
}
```

