# Testing

The test suite runs with a dedicated settings module that needs no
environment variables (in-memory SQLite, dummy Stripe keys, local email):

```bash
python manage.py test --settings=erp.settings_test
```

CI runs the same command on every push and pull request
(`.github/workflows/tests.yml`).

## Layout

- `carts/tests/` — cart API tests (`test_carts.py`) and pricing unit tests
  (`test_totals.py`): percentage/fixed discounts, exclusions, minimum order
  value, preorder pricing.
- `discounts/tests.py` — discount status (active/expired/scheduled/inactive)
  and manager filters.
- `checkout/tests.py` — shipping cost, order totals and the Stripe payload
  (what the customer sees must equal what Stripe charges).
- `shipping/tests.py` — shipping option pricing and cart-total discount.
