# Changelog

## 0.2.1

- Preserve concurrent GJC config saves with exclusive publication and retained native inodes.
- Recover native moves interrupted during installation or restore; protect legacy installs during restore.
- Reject dangling GJC config targets whose parent directory is missing before native mutation.
- Refresh unmodified managed Copilot adapters after metadata changes and diagnose stale adapters.
- Preserve the original undo record across repeated Copilot refreshes.
- Handle scalar-to-array Copilot hints by safely retargeting owned links and diagnosing missing adapters.
- Reject redirected journal/backup directories and validate backup parents.
- Add regression tests for races, retained descriptors, interrupted native moves, refresh rollback and path boundaries.

## 0.2.0

- Add an interactive harness checklist to install and preview commands.
- Show CLI detection, preselected targets, multi-select and keyboard controls.
- Preserve explicit/headless/JSON workflows with --non-interactive support.
- Cancel safely before configuration changes and restore terminal modes.
- Add real PTY tests for selection, cancellation, empty selections and resizing.

## 0.1.0

- Add eleven native harness adapters and selected-harness skill wiring.
- Add read-only plans, JSON status, static wiring diagnosis, and one-command setup.
- Keep native settings/authentication/session ownership and protect existing variants.
- Add locked installation transactions, private backups, restore, and crash recovery.
- Handle GJC custom skill directories and Copilot array-valued argument hints.
- Preserve unrelated YAML aliases and suppress private parser warning output.
- Add isolated workflow tests and installed-wheel verification.
