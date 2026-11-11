# Jepo's Plugins

Claude Code plugins by jepo. This repository is also a plugin marketplace named `jepo-plugins`.

| Plugin | Version | Engine | What it does |
|---|---|---|---|
| [godot-lsp-bridge](#godot-lsp-bridge) | 1.0.1 | Godot 4 (GDScript) | GDScript code intelligence through the Godot editor's language server; fails safe and asks you to open the editor when it is closed |

## godot-lsp-bridge

Gives Claude Code's LSP tool go-to-definition, find-references, hover and document symbols for
`.gd` files by relaying to the Godot editor's built-in language server on `127.0.0.1:6005`.
Python standard library only; no netcat needed. Full details:
[plugins/godot-lsp-bridge/README.md](plugins/godot-lsp-bridge/README.md).

### Install

Needs `python` on the PATH. In a Claude Code session:

```
/plugin marketplace add jepo/Claude-Plugins
/plugin install godot-lsp-bridge@jepo-plugins
```

Then start a new session or run `/reload-plugins`.

### Update

Claude does not check GitHub for new releases by itself, so refresh the marketplace, then the
plugin:

- Claude desktop app: Discover > Code, update the `jepo-plugins` marketplace there, then start a
  new session or run `/reload-plugins`.
- Claude Code CLI: `/plugin marketplace update jepo-plugins`, then
  `/plugin update godot-lsp-bridge@jepo-plugins`, then `/reload-plugins`.

### Notes

- The Godot language server only runs while the editor has the project open. While it is closed,
  requests fail with a message asking you to open it, and the bridge reconnects by itself when
  you do; no restart is needed.
- Godot does not support workspace symbol search, go-to-implementation or call hierarchy. Those
  operations return an error naming the ones that do work.
- The "open the editor" message names the project: set `GODOT_LSP_PROJECT`, or it uses the name of
  the folder Claude Code was started in. `GODOT_LSP_HOST` and `GODOT_LSP_PORT` change the address.
- A bridge for another engine can copy `plugins/godot-lsp-bridge` and change the constants at the
  top of its scripts.

## Licence

MIT, see `LICENSE`.
