# contract/

The API contract with the storefront (next-casspea). The plan behind it, and
the bugs it exposed, are in next-casspea's `docs/plan-rediseno-seguro.md`.

| File | Source | Checked by |
|---|---|---|
| `frontend-api-calls.json` | Copied from `next-casspea/contract/`, where a test records every request the storefront can send | `erp/tests/test_frontend_contract.py`: each call must resolve to a view that accepts its method |
| `responses/*.json` | Written by `erp/tests/test_frontend_contract.py` from real responses (lists cut to one item, timestamps frozen) | The same test: the live responses must keep the same keys and JSON types |

A storefront redesign should not need any change here. If a test fails, the
API changed under the frontend.

## Accepting a deliberate change

```bash
UPDATE_CONTRACT=1 python manage.py test erp.tests.test_frontend_contract --settings=erp.settings_test
git diff contract/                     # review every line
cp contract/responses/*.json ../next-casspea/contract/responses/
```

When the storefront changes its calls, copy its
`contract/frontend-api-calls.json` here and run the suite.

Calls the storefront makes that the API cannot answer yet are listed in
`KNOWN_GAPS` in `erp/tests/test_frontend_contract.py`, each with its bug ID.
