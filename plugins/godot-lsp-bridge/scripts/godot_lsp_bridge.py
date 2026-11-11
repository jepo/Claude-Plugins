"""Fail-safe stdio <-> TCP relay between Claude Code and Godot's built-in GDScript language server.

Claude Code starts this as an LSP server over stdio. It relays to the editor's language server on
TCP, which only runs while the Godot editor has the project open. If the editor is closed, every
request gets a prompt error saying so, and the bridge keeps retrying in the background. On
reconnect it redoes the handshake and reopens the documents Claude has open.
stdout carries LSP messages only; logs go to a file. Standard library only.
"""
import json
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

# Engine-specific settings: a bridge for another engine changes these.
ENGINE = "Godot"
# Named in the 'open the editor' message: GODOT_LSP_PROJECT, else the project folder's name.
PROJECT = os.environ.get("GODOT_LSP_PROJECT") or Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).name
HOST = os.environ.get("GODOT_LSP_HOST", "127.0.0.1")
PORT = int(os.environ.get("GODOT_LSP_PORT", "6005"))
LOG_NAME = "godot_lsp_bridge.log"
DOWN_MESSAGE = (f"The {ENGINE} editor is not running or its language server is not reachable at "
                f"{HOST}:{PORT}. Ask the user to open the {PROJECT} project in the {ENGINE} editor "
                f"(the language server only runs while the editor is open), then retry.")
UP_MESSAGE = f"The {ENGINE} editor's language server is connected again."
CAPABILITIES = {
    "textDocumentSync": {"openClose": True, "change": 1, "save": {"includeText": False}},
    "definitionProvider": True, "referencesProvider": True, "hoverProvider": True,
    "documentSymbolProvider": True,  # no workspace symbols: Godot answers "Method not found"
    "completionProvider": {"triggerCharacters": [".", "$", "\"", "'"]},
}
# Tunables (environment overrides exist for the tests).
REQUEST_TIMEOUT = float(os.environ.get("GODOT_LSP_BRIDGE_TIMEOUT", "15"))
MAX_BACKOFF = float(os.environ.get("GODOT_LSP_BRIDGE_MAX_BACKOFF", "10"))
NOTICE_INTERVAL = 60.0
REQUEST_FAILED = -32803

OUT = sys.stdout.buffer
sys.stdout = sys.stderr  # a stray print() must never reach the protocol stream
_log_lock = threading.Lock()


def _open_log():
    candidates = [os.environ.get("GODOT_LSP_BRIDGE_LOG")]
    for base in (os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        if base and (Path(base) / ".claude" / "logs").is_dir():
            candidates.append(str(Path(base) / ".claude" / "logs" / LOG_NAME))
    for path in filter(None, candidates):
        try:
            if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
                os.replace(path, path + ".1")
            return open(path, "a", encoding="utf-8")
        except OSError:
            pass
    return None  # no log file: stay silent rather than risk filling an unread stderr pipe


LOG = _open_log()


def log(msg):
    if LOG:
        with _log_lock:
            try:
                LOG.write(time.strftime("%H:%M:%S ") + msg + "\n")
                LOG.flush()
            except Exception:
                pass


def frame(obj):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def parse_frame(buf):
    """Return (message or None, remaining buffer). A bad body yields {} so it is skipped."""
    head, sep, rest = buf.partition(b"\r\n\r\n")
    if not sep:
        return None, buf
    length = 0
    for line in head.split(b"\r\n"):
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length" and value.strip().isdigit():
            length = int(value.strip())
    if len(rest) < length:
        return None, buf
    try:
        return json.loads(rest[:length].decode("utf-8")), rest[length:]
    except ValueError:
        log("dropped an unparsable message")
        return {}, rest[length:]


def apply_change(text, change):
    """Apply one didChange content change (full, or a range edit in UTF-16 positions)."""
    if "range" not in change:
        return change["text"]

    def offset(pos):
        idx = 0
        for _ in range(pos["line"]):
            nl = text.find("\n", idx)
            if nl < 0:
                return len(text)
            idx = nl + 1
        end = text.find("\n", idx)
        line = text[idx:] if end < 0 else text[idx:end]
        units, i = pos["character"], 0
        while i < len(line) and units > 0:
            units -= 2 if ord(line[i]) > 0xFFFF else 1
            i += 1
        return idx + i

    start, end = offset(change["range"]["start"]), offset(change["range"]["end"])
    return text[:start] + change["text"] + text[end:]


class Bridge:
    def __init__(self):
        self.lock = threading.RLock()
        self.out_lock = threading.Lock()
        self.sock = None            # set only while the handshake with Godot is complete
        self.init_params = None     # Claude's initialize params, reused for every handshake
        self.initialized = threading.Event()
        self.pending = {}           # godot id -> (claude id, deadline)
        self.next_id = 0
        self.docs = {}              # uri -> {"languageId", "version", "text"}
        self.last_notice = 0.0
        self.notified_down = False

    # ---- output to Claude ----
    def to_claude(self, obj):
        try:
            with self.out_lock:
                OUT.write(frame(obj))
                OUT.flush()
        except Exception:
            log("stdout closed; exiting")
            os._exit(0)

    def error_to_claude(self, cid, message=DOWN_MESSAGE):
        self.to_claude({"jsonrpc": "2.0", "id": cid, "error": {"code": REQUEST_FAILED, "message": message}})

    def show(self, message, kind):
        self.to_claude({"jsonrpc": "2.0", "method": "window/showMessage",
                        "params": {"type": kind, "message": message}})

    def notice(self):
        """Tell Claude the editor is unreachable, at most once per NOTICE_INTERVAL."""
        with self.lock:
            now = time.monotonic()
            if self.last_notice and now - self.last_notice < NOTICE_INTERVAL:
                return
            self.last_notice, self.notified_down = now, True
        self.show(DOWN_MESSAGE, 2)

    # ---- output to Godot ----
    def to_godot(self, obj, sock=None):
        sock = sock or self.sock
        if sock is None:
            return False
        try:
            sock.sendall(frame(obj))
            return True
        except OSError as e:
            log("send to %s failed: %s" % (ENGINE, e))
            self.disconnected(sock)
            return False

    def disconnected(self, sock):
        with self.lock:
            if sock is not self.sock:
                return
            self.sock = None
            failed, self.pending = list(self.pending.values()), {}
        try:
            sock.close()
        except OSError:
            pass
        log("lost the %s connection; failing %d in-flight request(s)" % (ENGINE, len(failed)))
        for cid, _ in failed:
            self.error_to_claude(cid)
        self.notice()

    # ---- messages from Claude ----
    def from_claude(self, msg):
        method, cid = msg.get("method"), msg.get("id")
        if method is None:
            return  # a response to nothing we asked, or an empty/bad message
        params = msg.get("params") or {}
        if cid is None:
            return self.claude_notification(method, params, msg)
        if method == "initialize":
            self.init_params = params if isinstance(params, dict) else {}
            self.to_claude({"jsonrpc": "2.0", "id": cid, "result": {
                "capabilities": CAPABILITIES, "serverInfo": {"name": "godot-lsp-bridge"}}})
            self.initialized.set()
        elif method == "shutdown":
            self.to_claude({"jsonrpc": "2.0", "id": cid, "result": None})
        else:
            with self.lock:
                sock = self.sock
                if sock is not None:
                    self.next_id += 1
                    gid = self.next_id
                    self.pending[gid] = (cid, time.monotonic() + REQUEST_TIMEOUT)
            if sock is None:
                self.error_to_claude(cid)
                self.notice()
            else:
                self.to_godot(dict(msg, id=gid), sock)

    def claude_notification(self, method, params, msg):
        if method == "exit":
            log("exit received")
            os._exit(0)
        if method == "$/cancelRequest":
            with self.lock:
                gid = next((g for g, (c, _) in self.pending.items() if c == params.get("id")), None)
            if gid is not None:
                self.to_godot({"jsonrpc": "2.0", "method": method, "params": {"id": gid}})
            return
        with self.lock:
            td = params.get("textDocument") or {}
            uri = td.get("uri")
            if method == "textDocument/didOpen":
                self.docs[uri] = {"languageId": td.get("languageId", "gdscript"),
                                  "version": td.get("version", 0), "text": td.get("text", "")}
            elif method == "textDocument/didClose":
                self.docs.pop(uri, None)
            elif method == "textDocument/didChange" and uri in self.docs:
                doc = self.docs[uri]
                for change in params.get("contentChanges", []):
                    doc["text"] = apply_change(doc["text"], change)
                doc["version"] = td.get("version", doc["version"])
                # Godot always gets the full text, whatever kind of change Claude sent.
                msg = {"jsonrpc": "2.0", "method": method, "params": {
                    "textDocument": {"uri": uri, "version": doc["version"]},
                    "contentChanges": [{"text": doc["text"]}]}}
            sock = self.sock
        if sock is not None and method != "initialized":
            self.to_godot(msg, sock)

    # ---- the Godot side: connect, handshake, read ----
    def godot_loop(self):
        self.initialized.wait()
        delay, first = 1.0, True
        while True:
            try:
                sock = socket.create_connection((HOST, PORT), timeout=3)
                sock.settimeout(5)
                buf = self.handshake(sock)
                delay = 1.0
                self.read_loop(sock, buf)
            except Exception as e:
                log("%s not reachable: %s" % (ENGINE, e))
                if first:
                    self.notice()
            first = False
            time.sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF)

    def recv_message(self, sock, buf, deadline=None):
        while True:
            msg, buf = parse_frame(buf)
            if msg is not None:
                return msg, buf
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                if deadline and time.monotonic() > deadline:
                    raise TimeoutError("no answer to initialize")
                if sock is not self.sock and deadline is None:
                    raise ConnectionError("connection replaced")
                continue
            if not chunk:
                raise ConnectionError("connection closed")
            buf += chunk

    def handshake(self, sock):
        params = dict(self.init_params)
        params["processId"] = os.getpid()
        if not params.get("rootUri"):
            folders = params.get("workspaceFolders") or []
            root = folders[0]["uri"] if folders else Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).as_uri()
            params["rootUri"] = root
        frame_ok = self.to_godot({"jsonrpc": "2.0", "id": "bridge-init", "method": "initialize", "params": params}, sock)
        if not frame_ok:
            raise ConnectionError("could not send initialize")
        buf, deadline = b"", time.monotonic() + 10
        while True:
            msg, buf = self.recv_message(sock, buf, deadline)
            if "method" in msg and "id" in msg:
                self.to_godot({"jsonrpc": "2.0", "id": msg["id"], "result": None}, sock)
            elif msg.get("id") == "bridge-init":
                break
        with self.lock:  # replay under the lock so no didChange slips between snapshot and switch-over
            self.to_godot({"jsonrpc": "2.0", "method": "initialized", "params": {}}, sock)
            for uri, doc in self.docs.items():
                self.to_godot({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
                    "textDocument": dict(doc, uri=uri)}}, sock)
            self.sock = sock
        log("connected to %s at %s:%d; reopened %d document(s)" % (ENGINE, HOST, PORT, len(self.docs)))
        if self.notified_down:
            self.notified_down = False
            self.show(UP_MESSAGE, 3)
        return buf

    def read_loop(self, sock, buf):
        try:
            while True:
                msg, buf = self.recv_message(sock, buf)
                try:
                    self.from_godot(msg, sock)
                except Exception:
                    log("error handling a %s message: %s" % (ENGINE, traceback.format_exc()))
        except Exception as e:
            log("read from %s ended: %s" % (ENGINE, e))
            self.disconnected(sock)

    def from_godot(self, msg, sock):
        method, gid = msg.get("method"), msg.get("id")
        if method is not None and gid is not None:  # server-to-client request: answer it here
            self.to_godot({"jsonrpc": "2.0", "id": gid, "result": None}, sock)
        elif method is not None:
            if method.startswith(("textDocument/", "window/", "$/")):
                self.to_claude(msg)
        else:
            with self.lock:
                entry = self.pending.pop(gid, None)
            if entry is None:
                log("dropped a response for unknown id %r" % (gid,))
            else:
                self.to_claude(dict(msg, id=entry[0]))

    def timeout_loop(self):
        while True:
            time.sleep(0.25)
            now = time.monotonic()
            with self.lock:
                expired = [g for g, (_, d) in self.pending.items() if d < now]
                entries = [(g, self.pending.pop(g)[0]) for g in expired]
            for gid, cid in entries:
                self.error_to_claude(cid, "The %s language server did not answer within %ds. If the editor is "
                                          "busy or frozen, ask the user to check it, then retry." % (ENGINE, REQUEST_TIMEOUT))
                self.to_godot({"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": gid}})


def main():
    if sys.platform == "win32":
        import msvcrt
        msvcrt.setmode(0, os.O_BINARY)
        msvcrt.setmode(1, os.O_BINARY)
    bridge = Bridge()
    for target in (bridge.godot_loop, bridge.timeout_loop):
        threading.Thread(target=target, daemon=True).start()
    log("started; %s at %s:%d" % (ENGINE, HOST, PORT))
    stdin, buf = sys.stdin.buffer, b""
    while True:
        chunk = stdin.read1(65536)
        if not chunk:
            log("stdin closed; exiting")
            return
        buf += chunk
        while True:
            msg, buf = parse_frame(buf)
            if msg is None:
                break
            try:
                bridge.from_claude(msg)
            except Exception:
                log("error handling a message: " + traceback.format_exc())
                if isinstance(msg, dict) and msg.get("id") is not None and msg.get("method"):
                    bridge.error_to_claude(msg["id"], "Internal bridge error; see " + LOG_NAME)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        log("fatal: " + traceback.format_exc())
    finally:
        try:
            OUT.flush()
        except Exception:
            pass
        os._exit(0)
