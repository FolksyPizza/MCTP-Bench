#!/usr/bin/env python3
"""Live monitor panel for a running sweep.

Connects to the runner's telemetry socket, reads the status snapshot, and redraws a compact
dashboard on an interval. Read-only: it never affects the sweep, and it reconnects on its own if
the runner has not started yet or has finished.

    python monitor.py [--host 127.0.0.1] [--port 8765] [--interval 1]

To watch a sweep on the GPU host from your laptop, forward the port over SSH:
    ssh -N -L 8765:127.0.0.1:8765 gpu     # then run monitor.py locally
"""
from __future__ import annotations

import argparse
import json
import socket
import time


def fetch(host: str, port: int, timeout: float = 2.0):
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    line = buf.split(b"\n", 1)[0].decode(errors="replace")
    return json.loads(line) if line else {}


def _fmt(seconds) -> str:
    if seconds is None:
        return "?"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else (f"{m}m{sec:02d}s" if m else f"{sec}s")


def _bar(done: int, total: int, width: int = 40) -> str:
    if not total:
        return "[" + " " * width + "]"
    filled = int(width * done / total)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def render(st: dict) -> str:
    if not st:
        return "waiting for telemetry ..."
    done, total = st.get("done", 0), st.get("total", 0)
    pct = (100.0 * done / total) if total else 0.0
    tallies = st.get("tallies", {})
    cur = st.get("current", {})
    age = time.time() - st.get("updated", time.time())
    state = ("FINISHED" if not st.get("running", True)
             else "STALE" if age > 30 else "running")
    lines = [
        f"  MCTP-Bench monitor — suite={st.get('suite','?')}  [{state}]",
        f"  models: {', '.join(st.get('models', []))}",
        f"  conditions: {', '.join(st.get('conditions', []))}",
        "",
        f"  {_bar(done, total)} {done}/{total} ({pct:.1f}%)",
        f"  rate {st.get('rate_s', 0):.1f}s/run   elapsed {_fmt(st.get('elapsed_s'))}   "
        f"ETA {_fmt(st.get('eta_s'))}",
        f"  pass {tallies.get('pass', 0)}   fail {tallies.get('fail', 0)}   "
        f"unscored {tallies.get('none', 0)}   error {tallies.get('error', 0)}",
        "",
        f"  current: {cur.get('model','-')}  {cur.get('condition','-')}  {cur.get('task','-')}",
        f"  last:    {st.get('last','-')}",
        f"  (updated {age:.0f}s ago)",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()
    print("\033[2J", end="")  # clear once
    while True:
        try:
            st = fetch(args.host, args.port)
            body = render(st)
        except (ConnectionRefusedError, OSError):
            body = (f"waiting for runner on {args.host}:{args.port} ... "
                    "(start a sweep, or check the SSH tunnel)")
        except Exception as e:
            body = f"monitor error: {type(e).__name__}: {e}"
        print("\033[H\033[2J", end="")  # home + clear
        print(body, flush=True)
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
