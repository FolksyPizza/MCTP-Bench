"""Live telemetry over a socket, for an external monitor panel.

The runner starts a small TCP server on localhost and updates a status snapshot as it works;
a monitor client (`monitor.py`) connects and renders it. On each connection the server writes the
current snapshot as one line of JSON and closes — so the monitor simply reconnects on an interval,
and the protocol stays trivial and robust (a dropped monitor never affects the run).

Telemetry is best-effort: if the port is taken or sockets are unavailable, `start()` returns a
no-op server and the sweep proceeds unaffected.
"""
from __future__ import annotations

import json
import socketserver
import threading
import time


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.wfile.write((json.dumps(self.server.snapshot()) + "\n").encode())
        except Exception:
            pass


class _NullTelemetry:
    port = None

    def update(self, **kw):
        pass

    def stop(self):
        pass


class TelemetryServer:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._status = {}
        self._lock = threading.Lock()
        self._srv = None
        self._thread = None

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._status)

    def update(self, **kw) -> None:
        with self._lock:
            self._status.update(kw)
            self._status["updated"] = time.time()

    def start(self) -> "TelemetryServer":
        server = socketserver.ThreadingTCPServer((self.host, self.port), _Handler,
                                                 bind_and_activate=False)
        server.allow_reuse_address = True
        server.daemon_threads = True
        server.snapshot = self.snapshot
        server.server_bind()
        server.server_activate()
        self._srv = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._srv:
            try:
                self._srv.shutdown()
                self._srv.server_close()
            except Exception:
                pass


def start(host: str = "127.0.0.1", port: int = 8765):
    """Start a telemetry server, or return a no-op one if the socket can't be bound."""
    try:
        return TelemetryServer(host, port).start()
    except OSError as e:
        print(f"[telemetry] disabled ({type(e).__name__}: {e}); is the port in use?")
        return _NullTelemetry()
