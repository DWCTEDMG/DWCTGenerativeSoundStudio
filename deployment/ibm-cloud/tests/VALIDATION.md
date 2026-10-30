# Candidate validation record

Validated locally on 2026-10-29 from base 3ec838476e94d78e271aea6200e6cfe88b2b3e7d.

- Terraform 1.9.8 fmt -check -recursive: passed.
- Terraform init -backend=false: passed, IBM provider 2.5.0.
- Terraform validate: passed without warnings after correcting boot volume size and metadata service configuration against the installed provider schema.
- Provider lock checksums obtained for Windows amd64 and Linux amd64.
- Package tests: 2 passed (manifest consistency/working directory and network/auth configuration boundaries).
- Candidate archive generated and root manifest/Terraform entry presence checked by package.py.
- git diff --check: passed.
- Docker daemon unavailable: `open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.` No container build, live health check, TLS handshake or backend integration pass is claimed.
- CI includes actual backend build and health/authentication smoke tests; remote CI execution is not yet verified.
- IBM credentials and paid deployment were not used. Cloud-init, live resource availability, least-privilege IAM, Windows TLS trust and Catalog deployment remain unverified.
- Catalog JSON is based on IBM's documented product/flavor structure. Full IBM manifest schema validation, imported input/IAM metadata and onboarding review remain outstanding.
- No release tag or public release created. Version 1.0.0 is a candidate designation.

The deployment does not yet satisfy every requested acceptance criterion. Optional COS/separate volumes, managed monitoring and GPU support are deferred. The source archive is infrastructure-only and requires a customer-built immutable backend image.
