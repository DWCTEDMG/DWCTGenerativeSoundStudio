# Contributing

## Dev setup
- Use Node >= 18 (or the version specified in project docs)
- Use `pnpm@10.33.0` for `studio/edmg-studio/` (`corepack enable` once first if `pnpm` is unavailable)
- Use Python 3.11 for the backend

## Code style
### Node/TS (studio/edmg-studio)
- Format with Prettier
- Lint with ESLint
- Typecheck with `pnpm run typecheck`
- Use `pnpm run check:tooling` to confirm the package manager, lockfile, and release metadata guardrails are intact

### Python (studio/edmg-studio/python_backend)
- Format + lint with Ruff
- Run tests with pytest

## Commands (recommended)
### Node/TS
- `pnpm install --frozen-lockfile`
- `pnpm run check:tooling`
- `pnpm run typecheck`
- `pnpm test`
- `pnpm run dev`
- After changing release/build glue: `pnpm run check:release-metadata`

### Python (from python_backend dir)
- `python -m ruff check .`
- `python -m ruff format .`
- `pytest`

## Pull requests
- Keep changes focused
- Include tests for behavior changes
- Update docs if you change API shape or UX
