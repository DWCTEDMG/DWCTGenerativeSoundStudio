# Contributing

Read the [stable branch and preview policy](docs/BRANCH_POLICY.md) before opening a pull request.
Report security issues privately as described in [SECURITY.md](SECURITY.md), never in a public issue.

## Dev setup
- Use Node >= 18 (or the version specified in project docs)
- Use `pnpm@10.33.0` for `studio/edmg-studio/` (`corepack enable` once first if `pnpm` is unavailable)
- Use Python 3.12 from the repository `.python-version`
- Use `uv` 0.11.28 and the committed backend `uv.lock`

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
- `uv lock --check`
- `uv sync --frozen --extra cpu --extra core --extra audio --group test --group lint`
- `uv run --frozen --extra cpu --group lint ruff check .`
- `uv run --frozen --extra cpu --group lint ruff format --check .`
- `uv run --frozen --extra cpu --extra core --extra audio --group test python -m pytest`

Select exactly one of `cpu`, `directml`, or `cuda`. Do not inject a PyTorch
index or install a package outside the lock. Dependency changes must update
`pyproject.toml` and `uv.lock` together; see
[`docs/PYTHON_TOOLCHAIN.md`](docs/PYTHON_TOOLCHAIN.md).

## Pull requests
- Keep changes focused
- Include tests for behavior changes
- Update docs if you change API shape or UX
- Target the documented integration channel; promotion to protected `main` happens through a separate reviewed pull request
- Include compatibility and rollback notes when changing persisted project data, render paths, or provider contracts
