# Test fixture inventory

The canonical small fixture set is `tests/fixtures/day1/`. Its manifest records byte sizes, SHA-256
digests, media types, expected properties, origin, and license. The files are deliberately tiny so
contract and compatibility tests run in a clean clone without downloading user media or model data.

## Rules

- Prefer synthetic inputs with deterministic generators and explicit redistribution terms.
- Keep each Day 1 payload under 64 KiB and reject network or absolute-path references.
- Update the golden manifest and tests in the same change as any payload byte change.
- Never commit user media, credentials, proprietary model output, or license-gated weights as a
  general test fixture.
- Large or realistic integration fixtures live outside the Day 1 inventory and need separately
  recorded provenance before redistribution or release packaging.

Run the inventory gate from the repository root:

```powershell
py -3.12 scripts/generate_day1_fixtures.py --check
py -3.12 -m pytest tests/test_day1_fixture_inventory.py -q
```
