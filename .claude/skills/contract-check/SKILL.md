---
name: contract-check
description: Compare your code or API calls against OPS/CONTRACT.md before integrating.
---
1. Read `OPS/CONTRACT.md` (note its version).
2. For each route, collection field, pack field or directive field you use, confirm it matches the contract exactly (names, types, required fields, error codes).
3. For the real API, compare responses against `mock/app.py` shapes.
4. Report mismatches as a list. Do not change the contract yourself: append to `OPS/BLOCKERS.md` for Greatness.
