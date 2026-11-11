# lsp-bridges

Claude Code plugins that connect Claude to a game engine's built-in language server. Each lives in
`plugins/<name>/`; this folder is also a local plugin marketplace (`.claude-plugin/marketplace.json`).

| Plugin | Engine | What it does |
|---|---|---|
| [godot-lsp-bridge](plugins/godot-lsp-bridge/README.md) | Godot 4 (GDScript) | Relays to the editor's language server on port 6005, fails safe and asks the user to open the editor when it is closed |

A bridge for another engine can copy `plugins/godot-lsp-bridge` and change the constants at the top
of its scripts.

## Install

In a Claude Code session (or `claude plugin ...` in a terminal), with the Godot editor open:

```
/plugin marketplace add jepo/Godot-LSP-Bridge
/plugin install godot-lsp-bridge@lsp-bridges
```

Then start a new session or run `/reload-plugins`. For a one-session trial from a local clone:
`claude --plugin-dir <clone>/plugins/godot-lsp-bridge`.

## Licence

MIT, see `LICENSE`.
