# Jepo's Plugins

Claude Code plugins by jepo. Each lives in `plugins/<name>/`; this repository is also a plugin
marketplace named `jepo-plugins` (`.claude-plugin/marketplace.json`). So far they all connect Claude
to a game engine's built-in language server.

| Plugin | Engine | What it does |
|---|---|---|
| [godot-lsp-bridge](plugins/godot-lsp-bridge/README.md) | Godot 4 (GDScript) | Relays to the editor's language server on port 6005, fails safe and asks the user to open the editor when it is closed |

A bridge for another engine can copy `plugins/godot-lsp-bridge` and change the constants at the top
of its scripts.

## Install

In a Claude Code session (or `claude plugin ...` in a terminal), with the Godot editor open:

```
/plugin marketplace add jepo/Claude-Plugins
/plugin install godot-lsp-bridge@jepo-plugins
```

Then start a new session or run `/reload-plugins`. For a one-session trial from a local clone:
`claude --plugin-dir <clone>/plugins/godot-lsp-bridge`.

## Versioning

Each plugin has its own version, in `plugins/<name>/.claude-plugin/plugin.json` (not in
`marketplace.json`). Claude Code caches installed plugins by that version, so every released change
bumps it: patch for bug fixes and minor tweaks, minor for new features, major only by explicit
decision. A new plugin gets its own folder under `plugins/` and its own entry in
`.claude-plugin/marketplace.json`.

## Licence

MIT, see `LICENSE`.
