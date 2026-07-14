# Security policy

## Supported versions

Security fixes are applied to the current development line and the latest supported Studio release.
Older source snapshots, experimental model adapters, and third-party runtimes may not receive fixes.

| Version | Supported |
|---|---|
| `1.1.x` and current `main` | Yes |
| Earlier versions | No |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or exposed credential. Use the repository's
private **Report a vulnerability** flow under GitHub Security Advisories. Include:

- the affected version or commit;
- the component and supported setup involved;
- reproduction steps or a minimal proof of concept;
- the impact and any known mitigations; and
- whether credentials, personal media, model licenses, or remote providers are involved.

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
