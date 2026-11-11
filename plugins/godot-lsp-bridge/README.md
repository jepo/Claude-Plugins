# godot-lsp-bridge

A Claude Code plugin that gives Claude GDScript code intelligence (definition, references,
hover, document symbols, completion, diagnostics) for `.gd` files. It relays between
Claude Code (LSP over stdio) and the Godot editor's built-in language server (LSP over TCP,
`127.0.0.1:6005`). Python standard library only; no netcat needed.

- `scripts/godot_lsp_bridge.py`: the relay Claude Code starts as the `gdscript` language server.
- `scripts/godot_lsp_check.py`: SessionStart hook. Prints one line saying whether the editor's
  language server is reachable; always exits 0.
- `test_bridge.py`: tests.

The Godot language server only runs while the Godot editor is open with the project loaded. The
bridge connects to it as one more client, alongside the editor's own script editor.

## Fail-safe behaviour

- The bridge never fails Claude's startup: it answers `initialize` itself at once, even when Godot
  is closed, then connects to Godot in the background, retrying every 1 s growing to 10 s.
- While Godot is unreachable, every request gets an immediate error saying the Godot editor is not
  running and the user should open the project in it, plus a `window/showMessage` with
  the same text at most once a minute.
- If Godot closes mid-session, in-flight requests fail at once with that error and the bridge
  reconnects. On reconnect it redoes the handshake with the original `rootUri`, reopens every
  document Claude has open (with the latest text, incremental edits applied) and sends a
  "connected again" `window/showMessage`.
- Each relayed request times out after 15 s with an error. Requests Godot sends to the client are
  answered with `null` locally. Responses for unknown ids are dropped.
- stdout carries LSP messages only. Logs go to `.claude/logs/godot_lsp_bridge.log` in the project
  (or the file named by `GODOT_LSP_BRIDGE_LOG`), never to stdout. It exits 0 on `exit` or when
  stdin closes.

Settings: `GODOT_LSP_HOST` and `GODOT_LSP_PORT` (defaults `127.0.0.1`, `6005`). The engine name,
port and the "open the editor" wording are constants at the top of each script, so a bridge for
another engine can copy them.

## Install

`python` must be on the PATH of the shell that starts Claude Code. From the folder that holds this
plugin (the marketplace is `../../.claude-plugin/marketplace.json`), in a Claude Code session:

```
/plugin marketplace add jepo/Claude-Plugins
/plugin install godot-lsp-bridge@jepo-plugins
```

(or `claude plugin marketplace add ...` / `claude plugin install ...` in a terminal). For one
session without installing: `claude --plugin-dir <path>/plugins/godot-lsp-bridge`. A plugin from a
local marketplace runs in place, so edits apply at the next session start or after
`/reload-plugins`. Load errors show under `/plugin` > Errors, or with `claude --debug`.

The message that asks the user to open the editor names the project: set `GODOT_LSP_PROJECT`, or it
uses the name of the folder Claude Code was started in.

## Tests

From this folder:

```
python -I test_bridge.py
```

The tests drive the bridge over stdio against a fake language server on a free port, covering
startup with Godot closed, error and showMessage throttling, relaying and id mapping, dropped and
server-initiated messages, timeouts, a mid-session drop with reconnect and document replay,
shutdown/exit/EOF, and the check script. The last test runs a read-only smoke test against the
real Godot editor on port 6005; it needs the editor open and `GODOT_LSP_TEST_FILE` (a `.gd` file in
the open project) and `GODOT_LSP_TEST_SYMBOL` (a name declared there and used elsewhere), and is
skipped otherwise.
