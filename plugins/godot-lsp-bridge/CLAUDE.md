# godot-lsp-bridge: rules for working on this plugin

The repository-wide rules in [../../CLAUDE.md](../../CLAUDE.md) apply too. Behaviour, settings and
install details are in [README.md](README.md).

- Fail-safe behaviour is the point of the bridge: it must never crash, hang or exit non-zero, must
  write only LSP frames to stdout, and must log to a file only.
- Keep the scripts standard-library Python. The user's Windows machine has `python` but no
  `python3` and no `nc`.
- Never close, kill, restart or launch the user's Godot editor. Test down/up behaviour with the fake
  server in the tests, or ask the user to close or open the editor.
- Run the tests from this folder with `python -I test_bridge.py`. The real-editor smoke test runs
  when `GODOT_LSP_TEST_FILE` and `GODOT_LSP_TEST_SYMBOL` are set, for example
  `C:\Users\jepo\Documents\Projects\GalaxyGame\scripts\systems\save_games.gd` and `SlotPath`. It is
  read-only and safe to run while the editor is open.
- The GalaxyGame project denies reading `.claude/logs` through the Read tool; use Bash to look at
  the bridge log there (`.claude/logs/godot_lsp_bridge.log`).
