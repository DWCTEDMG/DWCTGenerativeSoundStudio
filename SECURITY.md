# Security Policy

## Supported versions

Security fixes are applied on the active Studio development branch and any
currently published release candidate. Older experimental worktrees are not
guaranteed to receive backports.

## Reporting a vulnerability

Do **not** open a public GitHub issue for security-sensitive reports.

Email or message the maintainers privately with:

- affected component (Electron shell, FastAPI backend, launchers, packaging);
- impact and reproduction steps;
- whether secrets, project data, or remote-bind auth can be abused;
- your preferred contact for follow-up.

Please allow a reasonable window for triage before public disclosure.

## Hardening notes for operators

- Prefer loopback backend binds for local Studio use.
- For non-loopback backends, set `EDMG_BACKEND_AUTH_TOKEN` and
  `EDMG_BACKEND_AUTH_MODE=required`.
- Never place backend auth tokens or provider API keys in frontend `VITE_*`
  variables or committed env files.
- Keep Studio Home, model caches, and logs on trusted local storage.
- Treat experimental model lanes and remote providers as untrusted until their
  license, provenance, and network boundaries are reviewed.
