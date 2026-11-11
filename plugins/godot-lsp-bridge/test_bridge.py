"""Tests for scripts/godot_lsp_bridge.py. Run: python -I test_bridge.py

Drives the bridge over stdio like Claude Code does, against a fake language server on a free port.
Finally, if the real Godot editor is listening on 6005, runs a read-only smoke test against it.
"""
import json
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRIDGE = HERE / "scripts" / "godot_lsp_bridge.py"
ROOT_URI = HERE.as_uri()  # any folder will do for the fake-server tests
GAME = "TestGame"  # the project name the messages should mention (set through GODOT_LSP_PROJECT)
LOG = Path(tempfile.gettempdir()) / "godot_lsp_bridge_test.log"


def frame(obj):
    body = json.dumps(obj).encode()
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def read_frames(stream, sink, raw_errors):
    """Parse a byte stream strictly as LSP frames; anything else is recorded as an error."""
    while True:
        header = b""
        while not header.endswith(b"\r\n\r\n"):
            try:
                ch = stream.read(1)
            except OSError:  # the peer reset the connection
                return
            if not ch:
                if header:
                    raw_errors.append(header)
                return
            header += ch
        if not header.startswith(b"Content-Length: "):
            raw_errors.append(header)
            return
        body = stream.read(int(header.split(b":")[1]))
        sink.put(json.loads(body))


class FakeServer:
    """A stand-in for Godot's language server. Can be stopped (port closed) and restarted."""

    def __init__(self, port=0):
        self.port, self.received, self.conns, self.listener = port, queue.Queue(), [], None
        self.start()

    def start(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", self.port))
        self.port = self.listener.getsockname()[1]
        self.listener.listen()
        threading.Thread(target=self.accept_loop, args=(self.listener,), daemon=True).start()

    def stop(self):
        self.listener.close()
        for c in self.conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
                c.close()
            except OSError:
                pass
        self.conns = []

    def accept_loop(self, listener):
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            self.conns.append(conn)
            threading.Thread(target=self.serve, args=(conn,), daemon=True).start()

    def serve(self, conn):
        stream = conn.makefile("rb")
        sink = queue.Queue()
        threading.Thread(target=read_frames, args=(stream, sink, []), daemon=True).start()
        send = lambda obj: conn.sendall(frame(obj))
        while True:
            try:
                msg = sink.get(timeout=30)
            except queue.Empty:
                return
            self.received.put(msg)
            m, i = msg.get("method"), msg.get("id")
            try:
                if m == "initialize":
                    send({"jsonrpc": "2.0", "id": "srv-1", "method": "gdscript_client/changeWorkspace", "params": {}})
                    send({"jsonrpc": "2.0", "method": "gdscript/capabilities", "params": {}})
                    send({"jsonrpc": "2.0", "id": i, "result": {"capabilities": {"hoverProvider": True}}})
                elif m == "textDocument/documentSymbol":
                    send({"jsonrpc": "2.0", "id": 99999, "result": "stale"})  # unknown id: must be dropped
                    send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                          "params": {"uri": "file:///C:/x.gd", "diagnostics": []}})
                    send({"jsonrpc": "2.0", "id": i, "result": [{"name": "Sym", "echo_id": i}]})
                elif m == "textDocument/hover":
                    pass  # never answers: used for timeout and mid-request drop tests
            except OSError:
                return

    def expect(self, pred, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = self.received.get(timeout=0.1)
            except queue.Empty:
                continue
            if pred(msg):
                return msg
        raise AssertionError("fake server did not receive the expected message")


class Client:
    """Plays Claude Code: talks to the bridge over its stdin/stdout."""

    def __init__(self, port, timeout="2", host="127.0.0.1"):
        env = dict(os.environ, GODOT_LSP_PROJECT=GAME, GODOT_LSP_HOST=host, GODOT_LSP_PORT=str(port), GODOT_LSP_BRIDGE_TIMEOUT=timeout,
                   GODOT_LSP_BRIDGE_MAX_BACKOFF="1", GODOT_LSP_BRIDGE_LOG=str(LOG))
        self.proc = subprocess.Popen([sys.executable, "-I", str(BRIDGE)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.inbox, self.raw_errors, self.seen = queue.Queue(), [], []
        threading.Thread(target=read_frames, args=(self.proc.stdout, self.inbox, self.raw_errors), daemon=True).start()

    def send(self, obj):
        self.proc.stdin.write(frame(obj) if isinstance(obj, dict) else obj)
        self.proc.stdin.flush()

    def request(self, rid, method, params=None):
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})

    def notify(self, method, params=None):
        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def expect(self, pred, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = self.inbox.get(timeout=0.1)
            except queue.Empty:
                continue
            self.seen.append(msg)
            if pred(msg):
                return msg
        raise AssertionError("bridge did not send the expected message; saw %s" % self.seen[-5:])

    def response(self, rid, timeout=5):
        return self.expect(lambda m: m.get("id") == rid and "method" not in m, timeout)

    def drain(self, wait=0.5):
        time.sleep(wait)
        while not self.inbox.empty():
            self.seen.append(self.inbox.get())

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        assert not self.raw_errors, "non-LSP bytes on stdout: %r" % self.raw_errors


def is_show(text):
    return lambda m: m.get("method") == "window/showMessage" and text in m["params"]["message"]


def doc(uri, text, version=1):
    return {"textDocument": {"uri": uri, "languageId": "gdscript", "version": version, "text": text}}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------- tests

def test_startup_while_godot_closed_then_comes_up():
    port = free_port()
    c = Client(port)
    try:
        t = time.time()
        c.request(1, "initialize", {"rootUri": ROOT_URI, "capabilities": {}})
        caps = c.response(1)["result"]["capabilities"]
        assert time.time() - t < 2, "initialize was not answered immediately"
        for key in ("definitionProvider", "referencesProvider", "hoverProvider", "documentSymbolProvider",
                    "workspaceSymbolProvider", "completionProvider"):
            assert caps.get(key), key
        c.notify("initialized")
        c.notify("textDocument/didOpen", doc("file:///C:/proj/a.gd", "var a = 1\n"))
        t = time.time()
        c.request("r2", "textDocument/definition", {"textDocument": {"uri": "file:///C:/proj/a.gd"},
                                                     "position": {"line": 0, "character": 4}})
        err = c.response("r2")["error"]
        assert time.time() - t < 1, "error was not prompt"
        assert "not running" in err["message"] and GAME in err["message"], err
        c.expect(is_show("not running"))
        c.request(3, "textDocument/hover", {})
        assert "error" in c.response(3)
        c.drain()
        shows = [m for m in c.seen if m.get("method") == "window/showMessage"]
        assert len(shows) == 1, "showMessage not throttled: %d" % len(shows)
        assert c.proc.poll() is None, "bridge died while Godot was closed"
        server = FakeServer(port)  # Godot opens
        init = server.expect(lambda m: m.get("method") == "initialize", timeout=5)
        assert init["params"]["rootUri"] == ROOT_URI
        server.expect(lambda m: m.get("id") == "srv-1" and m.get("result") is None and "method" not in m)
        server.expect(lambda m: m.get("method") == "initialized")
        server.expect(lambda m: m.get("method") == "textDocument/didOpen"
                      and m["params"]["textDocument"]["uri"] == "file:///C:/proj/a.gd")
        c.expect(is_show("connected again"))
        c.request(4, "textDocument/documentSymbol", {"textDocument": {"uri": "file:///C:/proj/a.gd"}})
        assert c.response(4)["result"][0]["name"] == "Sym"
        server.stop()
    finally:
        c.close()


def test_relay_ids_drops_and_server_requests():
    server = FakeServer()
    c = Client(server.port)
    try:
        c.request("init", "initialize", {"rootUri": ROOT_URI, "capabilities": {}})
        c.response("init")
        c.notify("initialized")
        server.expect(lambda m: m.get("method") == "initialized")
        for rid in ("abc", 7):  # string and integer ids both come back unchanged
            c.request(rid, "textDocument/documentSymbol", {"textDocument": {"uri": "file:///C:/x.gd"}})
            res = c.response(rid)
            assert res["result"][0]["name"] == "Sym"
            if rid == "abc":
                assert isinstance(res["result"][0]["echo_id"], int), "Claude's id reached Godot unmapped"
        c.drain()
        assert [m for m in c.seen if m.get("method") == "textDocument/publishDiagnostics"], "notification not relayed"
        assert not [m for m in c.seen if m.get("id") == 99999], "a response for an unknown id was forwarded"
        assert not [m for m in c.seen if str(m.get("method", "")).startswith("gdscript")], "Godot-only message forwarded"
        # Garbage on stdin must not kill the bridge.
        c.send(b"Content-Length: 5\r\n\r\n{bad}")
        c.send(b"Content-Length: x\r\n\r\n")
        c.request(8, "textDocument/documentSymbol", {"textDocument": {"uri": "file:///C:/x.gd"}})
        assert "result" in c.response(8)
    finally:
        c.close()
        server.stop()


def test_request_timeout():
    server = FakeServer()
    c = Client(server.port, timeout="1.5")
    try:
        c.request(1, "initialize", {"rootUri": ROOT_URI})
        c.response(1)
        c.notify("initialized")
        server.expect(lambda m: m.get("method") == "initialized")
        t = time.time()
        c.request(2, "textDocument/hover", {})
        err = c.response(2, timeout=5)["error"]
        assert 1.2 < time.time() - t < 3, "timeout took %.1fs" % (time.time() - t)
        assert "did not answer" in err["message"]
        server.expect(lambda m: m.get("method") == "$/cancelRequest")
    finally:
        c.close()
        server.stop()


def test_drop_mid_session_and_replay():
    server = FakeServer()
    c = Client(server.port, timeout="10")
    a, b = "file:///C:/proj/a.gd", "file:///C:/proj/b.gd"
    try:
        c.request(1, "initialize", {"rootUri": ROOT_URI})
        c.response(1)
        c.notify("initialized")
        server.expect(lambda m: m.get("method") == "initialized")  # the bridge is through to "Godot"
        c.notify("textDocument/didOpen", doc(a, "line one\nline two\n"))
        c.notify("textDocument/didOpen", doc(b, "b\n"))
        c.notify("textDocument/didChange", {"textDocument": {"uri": a, "version": 2}, "contentChanges": [
            {"range": {"start": {"line": 1, "character": 5}, "end": {"line": 1, "character": 8}}, "text": "2"}]})
        sent = server.expect(lambda m: m.get("method") == "textDocument/didChange")
        assert sent["params"]["contentChanges"] == [{"text": "line one\nline 2\n"}], sent
        c.request(2, "textDocument/hover", {})  # in flight when Godot goes away
        server.expect(lambda m: m.get("method") == "textDocument/hover")
        t = time.time()
        server.stop()  # Godot closes
        err = c.response(2, timeout=3)["error"]
        assert time.time() - t < 2 and "not running" in err["message"]
        c.expect(is_show("not running"))
        c.request(3, "textDocument/definition", {})
        assert "not running" in c.response(3)["error"]["message"]
        # Edits while Godot is away are tracked: one incremental, one full, and b is closed.
        c.notify("textDocument/didChange", {"textDocument": {"uri": a, "version": 3}, "contentChanges": [
            {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 4}}, "text": "LINE"}]})
        c.notify("textDocument/didClose", {"textDocument": {"uri": b}})
        server.start()  # Godot comes back on the same port
        init = server.expect(lambda m: m.get("method") == "initialize", timeout=5)
        assert init["params"]["rootUri"] == ROOT_URI
        server.expect(lambda m: m.get("method") == "initialized")
        reopened = server.expect(lambda m: m.get("method") == "textDocument/didOpen")
        assert reopened["params"]["textDocument"]["uri"] == a
        assert reopened["params"]["textDocument"]["text"] == "LINE one\nline 2\n"
        assert reopened["params"]["textDocument"]["version"] == 3
        c.expect(is_show("connected again"))
        c.request(4, "textDocument/documentSymbol", {"textDocument": {"uri": a}})
        assert c.response(4)["result"][0]["name"] == "Sym"
        time.sleep(0.3)
        others = []
        while not server.received.empty():
            others.append(server.received.get())
        assert not [m for m in others if m.get("method") == "textDocument/didOpen"], "closed doc was replayed"
    finally:
        c.close()
        server.stop()


def test_shutdown_exit_and_eof():
    port = free_port()
    c = Client(port)
    c.request(1, "initialize", {"rootUri": ROOT_URI})
    c.response(1)
    c.request(2, "shutdown")
    assert c.response(2)["result"] is None
    c.notify("exit")
    assert c.proc.wait(timeout=3) == 0
    c.close()
    c = Client(port)
    c.proc.stdin.close()  # Claude goes away without a word
    assert c.proc.wait(timeout=3) == 0
    assert c.proc.stderr.read() == b"", "the bridge wrote to stderr"
    c.close()


def test_check_script():
    check = HERE / "scripts" / "godot_lsp_check.py"
    port = free_port()
    out = subprocess.run([sys.executable, "-I", str(check)], capture_output=True, text=True, timeout=10,
                         env=dict(os.environ, GODOT_LSP_PROJECT=GAME, GODOT_LSP_PORT=str(port)))
    assert out.returncode == 0 and "NOT reachable" in out.stdout and GAME in out.stdout, out
    assert len(out.stdout.strip().splitlines()) == 1
    server = FakeServer()
    out = subprocess.run([sys.executable, "-I", str(check)], capture_output=True, text=True, timeout=10,
                         env=dict(os.environ, GODOT_LSP_PORT=str(server.port)))
    server.stop()
    assert out.returncode == 0 and "is reachable" in out.stdout, out
    out = subprocess.run([sys.executable, "-I", str(check)], capture_output=True, text=True, timeout=10,
                         env=dict(os.environ, GODOT_LSP_PORT="not-a-port"))
    assert out.returncode == 0 and len(out.stdout.strip().splitlines()) == 1, out


def test_real_godot_smoke():
    """Needs the Godot editor open on a project. Set GODOT_LSP_TEST_FILE to a .gd file in it and
    GODOT_LSP_TEST_SYMBOL to a name declared there and used in other files; skipped otherwise."""
    file, symbol = os.environ.get("GODOT_LSP_TEST_FILE"), os.environ.get("GODOT_LSP_TEST_SYMBOL")
    if not file or not symbol:
        return "SKIPPED (set GODOT_LSP_TEST_FILE and GODOT_LSP_TEST_SYMBOL to run it)"
    try:
        socket.create_connection(("127.0.0.1", 6005), timeout=1).close()
    except OSError:
        return "SKIPPED (nothing listening on 127.0.0.1:6005)"
    target = Path(file).resolve()
    root = next((p for p in target.parents if (p / "project.godot").is_file()), target.parent)
    c = Client(6005, timeout="15")
    try:
        c.request(1, "initialize", {"processId": None, "rootUri": root.as_uri(), "capabilities": {}})
        c.response(1)
        c.notify("initialized")
        c.notify("textDocument/didOpen", doc(target.as_uri(), target.read_text(encoding="utf-8")))
        deadline = time.time() + 15
        while True:  # the bridge connects in the background; retry until it is through
            c.request("sym", "textDocument/documentSymbol", {"textDocument": {"uri": target.as_uri()}})
            res = c.response("sym", timeout=20)
            if "result" in res or time.time() > deadline:
                break
            time.sleep(1)
        assert res.get("result"), res
        names = [s.get("name") for s in res["result"]]
        children = sum(len(s.get("children") or []) for s in res["result"])
        lines = target.read_text(encoding="utf-8").splitlines()
        line = next((i for i, text in enumerate(lines)
                     if symbol in text and not text.lstrip().startswith("#")), None)
        assert line is not None, "%s not found in %s" % (symbol, target.name)
        col = lines[line].find(symbol) + 1
        c.request("refs", "textDocument/references", {"textDocument": {"uri": target.as_uri()},
                  "position": {"line": line, "character": col}, "context": {"includeDeclaration": True}})
        found = c.response("refs", timeout=20).get("result") or []
        files = {r["uri"].rsplit("/", 1)[-1] for r in found}
        return "documentSymbol: %s with %d members; references to %s: %d in %d files" % (
            names, children, symbol, len(found), len(files))
    finally:
        c.request(99, "shutdown")
        c.notify("exit")
        c.proc.wait(timeout=5)
        c.close()


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            t = time.time()
            try:
                note = fn()
                print("PASS %-45s %.1fs %s" % (name, time.time() - t, note or ""))
            except Exception as e:
                failed += 1
                print("FAIL %-45s %s: %s" % (name, type(e).__name__, e))
    print("log: %s" % LOG)
    sys.exit(1 if failed else 0)
