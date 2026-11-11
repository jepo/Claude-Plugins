"""SessionStart check: is the Godot editor's language server reachable? Prints one line, always exits 0."""
import os
import socket
import sys
from pathlib import Path

ENGINE = "Godot"
PROJECT = os.environ.get("GODOT_LSP_PROJECT") or Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).name

try:
    host = os.environ.get("GODOT_LSP_HOST", "127.0.0.1")
    port = int(os.environ.get("GODOT_LSP_PORT", "6005"))
    try:
        socket.create_connection((host, port), timeout=1.5).close()
        print(f"{ENGINE} language server is reachable at {host}:{port}; GDScript code intelligence "
              f"(definition, references, hover, symbols) is available for .gd files.")
    except OSError:
        print(f"{ENGINE} language server is NOT reachable at {host}:{port}: the {ENGINE} editor is not open "
              f"with the {PROJECT} project (its language server only runs while the editor is open). "
              f"GDScript code intelligence is unavailable until the user opens the {PROJECT} project in the "
              f"{ENGINE} editor; suggest that to the user if you need it.")
except Exception as e:  # never fail session startup
    print(f"{ENGINE} language server check skipped: {e}")
sys.exit(0)
