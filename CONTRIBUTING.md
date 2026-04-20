# Contributing

## Dev setup
- Use Node >= 18 (or the version specified in project docs)
- Use Python 3.11 for the backend

## Code style
### Node/TS (studio/edmg-studio)
- Format with Prettier
- Lint with ESLint
- Typecheck with `pnpm run typecheck` (`corepack enable` once first if `pnpm` is unavailable)

### Python (studio/edmg-studio/python_backend)
- Format + lint with Ruff
- Run tests with pytest

## Commands (recommended)
### Node/TS
- `pnpm run typecheck`
- `pnpm run dev`
- After adding scripts: `pnpm run lint`, `pnpm run format`, `pnpm test`

### Python (from python_backend dir)
- `python -m ruff check .`
- `python -m ruff format .`
- `pytest`

## Pull requests
- Keep changes focused
- Include tests for behavior changes
- Update docs if you change API shape or UX
