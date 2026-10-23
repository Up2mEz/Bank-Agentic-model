# Workspace layout

- Keep this project's source, tools, caches, downloads, databases, test fixtures,
  reports, and related checkouts under this repository root.
- Local Merchant tools and state belong in `.local/merchant-dev/` (Git ignored).
  Source `scripts/project-env.ps1` before running Merchant tooling. Do not create
  a new `D:\merchant-dev` directory or a second toolchain/cache elsewhere.
- Related Merchant repositories and worktrees belong in `repos/` (Git ignored).
  Preserve their own Git history; do not add them to this repository's index.
- Put generated runs and audit receipts in `outputs/<task-or-run>/`. Keep durable
  documentation in `docs/`, reusable scripts in `scripts/` or `tools/`, and
  reproducibility receipts with the artifacts they describe.
- The migration is complete. Four old paths remain as compatibility junctions
  pointing into this root, so old scripts and saved links still work without
  duplicate data. Use the canonical paths above for new work. See the receipt in
  `outputs/project-layout-20261022/`; never recursively delete a junction.
- Do not relocate running PostgreSQL data, SDKs in use, or checkouts being edited
  in another thread. Check processes and active threads before final migration.
- Remove verified installer archives after installation, keeping their version,
  source, size, and SHA-256 receipts. Do not delete source, database contents,
  evidence, original test oracles, releases, or uncommitted changes as cleanup.
- See `docs/PROJECT_LAYOUT_TH.md` for the layout and migration status.
