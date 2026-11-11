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
  (what the customer sees must equal what Stripe charges). Note that the
  payload tests cover `prepare_stripe_payload` (embedded checkout); the hosted
  checkout the shop uses builds its own copy in `checkout/stripe_views.py`.
- `shipping/tests.py` — shipping option pricing and cart-total discount.
- `erp/tests/test_frontend_contract.py` — the contract with the storefront:
  every call in `contract/frontend-api-calls.json` (copied from next-casspea)
  must reach a view that accepts its method, and the responses the shop is
  built on must keep the shape stored in `contract/responses/`. See
  [contract/README.md](contract/README.md).
- `erp/tests/test_known_issues.py` — known bugs, one test each (see below).

## Known bugs

A known bug is pinned by a test that describes the correct behaviour and is
marked `@expectedFailure`, so the suite stays green while the bug exists.
Fixing the bug makes the test pass, Django reports an "unexpected success"
and the run fails: delete the decorator and keep the test as a guard. IDs
(BUG-01, …) match the table in next-casspea's `docs/plan-rediseno-seguro.md`.

## Contract files

After a deliberate change to a response the storefront reads:

```bash
UPDATE_CONTRACT=1 python manage.py test erp.tests.test_frontend_contract --settings=erp.settings_test
git diff contract/
```

Then copy `contract/responses/` to next-casspea's `contract/responses/`.
