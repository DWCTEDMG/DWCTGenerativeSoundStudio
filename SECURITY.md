# Security Policy

## Supported versions

Security fixes are applied to the active Studio development branch and the latest supported Studio
release candidate. Older source snapshots, experimental model adapters, and third-party runtimes
may not receive fixes or backports.

| Version | Supported |
|---|---|
| `1.1.x` and current `main` | Yes |
| Earlier versions | No |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or exposed credential. Use the
repository's private **Report a vulnerability** flow under GitHub Security Advisories or contact
the maintainers privately. Include:

- the affected version or commit;
- the component and supported setup involved;
- reproduction steps or a minimal proof of concept;
- the impact and any known mitigations; and
- whether credentials, personal media, model licenses, project data, or remote providers are
  involved.

The project targets an acknowledgement within three business days. A fix timeline depends on
severity, reproducibility, affected releases, and upstream dependencies. Please allow a reasonable
remediation window before public disclosure.

## Scope and handling

The most useful reports concern Studio authentication, Electron IPC, unsafe file access, credential
storage or disclosure, dependency compromise, remote-provider boundaries, model-download integrity,
or code execution in supported install paths. Reports that require intentionally disabling documented
security controls may still be useful but should explain that precondition.

Never include real API keys, access tokens, personal audio, unreleased media, or proprietary model
weights in a report. Replace them with synthetic fixtures and revoke any credential that may have
been exposed.

## Hardening notes for operators

- Prefer loopback backend binds for local Studio use.
- For non-loopback backends, set `EDMG_BACKEND_AUTH_TOKEN` and
  `EDMG_BACKEND_AUTH_MODE=required`.
- Never place backend auth tokens or provider API keys in frontend `VITE_*` variables or committed
  env files.
- Keep Studio Home, model caches, and logs on trusted local storage.
- Treat experimental model lanes and remote providers as untrusted until their license, provenance,
  and network boundaries are reviewed.
