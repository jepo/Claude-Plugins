# Versioning

Read this before releasing a change to any plugin in this repository.

- Each plugin has its own version, in `plugins/<name>/.claude-plugin/plugin.json`. There is no
  repository-wide version, and `.claude-plugin/marketplace.json` carries none.
- Claude Code caches an installed plugin by that version, so a change released without a bump is
  not picked up by `/plugin update`. Bump the version in the same commit as the change.
- Which part to bump:
  - **Patch** (1.0.0 to 1.0.1): bug fixes and minor tweaks.
  - **Minor** (1.0.1 to 1.1.0): new features.
  - **Major** (1.x to 2.0.0): only when the owner explicitly decides on a major release.
- Changes that do not reach the installed plugin (the repository README, this file, tests only)
  need no bump.
- After a bump, update that plugin's Version cell in the table in `README.md` to match.
- A new plugin gets its own folder under `plugins/`, its own entry in
  `.claude-plugin/marketplace.json`, starts at 1.0.0, and gets a row in the `README.md` table and its
  own section below it.
