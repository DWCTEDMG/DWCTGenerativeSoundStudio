# UI automation qualification

`ui-automation-capabilities.json` is the repository-controlled harness contract for unpackaged and packaged WinUI runs. CI validates the contract but records `not-run-capability-missing`; it does not claim an interactive test ran.

An executing machine must provide Windows 10/11, an unlocked interactive desktop, an approved UI Automation driver (for example Windows Application Driver), and either a built unpackaged executable or an installed, trusted MSIX. A runner must emit a result using one of the manifest states and cover all `requiredSmokeCases`. Packaged mode additionally requires package identity; unsigned structural packages do not qualify.
