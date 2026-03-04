# Changelog

This folder holds the **MASTER_CHANGELOG.md**, which is the single internal changelog for production deployments.

- **When to update:** Add a new timestamped entry whenever you are about to push an update to production (e.g. after merging a feature branch to `main`).
- **What to include:** Summary of the change plus a **Production agent checklist**: markdown checkboxes (`- [ ]`) for every task the production agent must complete. Always include at least minimal items (e.g. "Confirm codebase changes", "Update local database" when schema changes exist). The agent checks off each box as done.
- **Workflow:** Merge to `main` → sync on production → production agent reads the latest changelog entry, works through the checklist (checking boxes), then restarts services when complete.
