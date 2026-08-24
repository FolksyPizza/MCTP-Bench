"""Run orchestration: checkpoint/resume, ETA/progress, and time-window gating.

A long sweep is thousands of runs. This module makes one interruptible and resumable, reports
where it is, and can confine work to a chosen part of the day.

- Manifest: an append-only log of completed run keys. Because every run is recorded the moment
  it finishes, a killed sweep loses at most the in-flight run; `--resume` skips everything in the
  manifest. It also covers the swarm tier, where per-stage records don't map to a single key.
- Progress: total / done / remaining, a rolling seconds-per-run rate, elapsed, and an ETA.
- WindowGate: an allowed clock window (e.g. 23:00-06:00, wrapping midnight); `wait_until_open`
  sleeps until inside it, so a sweep can be limited to off-hours.
"""
from __future__ import annotations

import datetime
import os
import signal
import threading
import time


def run_key(suite: str, task_id: str, condition: str, model: str, trial: int) -> str:
    return f"{suite}|{task_id}|{condition}|{model}|t{trial}"


class Manifest:
    """Append-only set of completed run keys, persisted under results/progress/."""

    def __init__(self, path: str):
        self.path = path
        self.done = set()
        self._lock = threading.Lock()   # add() is called from concurrent workers
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.done.add(line)
        self._fh = open(path, "a")

    def has(self, key: str) -> bool:
        return key in self.done

    def add(self, key: str) -> None:
        with self._lock:
            if key in self.done:
                return
            self.done.add(key)
            self._fh.write(key + "\n")
            self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


def fmt_duration(seconds) -> str:
    if seconds is None:
        return "?"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{sec:02d}s"
    return f"{sec}s"


class Progress:
    """Tracks completion and estimates time remaining from a rolling per-run rate."""

    def __init__(self, total: int, done: int = 0, window: int = 200):
        self.total = total
        self.done = done
        self.start = time.monotonic()
        self._durations = []
        self._window = window

    def tick(self, duration: float) -> None:
        self.done += 1
        self._durations.append(duration)
        if len(self._durations) > self._window:
            self._durations = self._durations[-self._window:]

    def rate(self) -> float:
        """Rolling average seconds per run."""
        return sum(self._durations) / len(self._durations) if self._durations else 0.0

    def remaining(self) -> int:
        return max(0, self.total - self.done)

    def eta_seconds(self):
        r = self.rate()
        return r * self.remaining() if r else None

    def line(self) -> str:
        elapsed = time.monotonic() - self.start
        pct = (100.0 * self.done / self.total) if self.total else 0.0
        return (f"progress {self.done}/{self.total} ({pct:.1f}%), {self.remaining()} left, "
                f"{self.rate():.1f}s/run, elapsed {fmt_duration(elapsed)}, "
                f"ETA {fmt_duration(self.eta_seconds())}")


class StopController:
    """Graceful stop: finish the current run, save, then stop — rather than aborting mid-run.

    A stop is requested two ways: a SIGINT (Ctrl-C) or SIGTERM, or the appearance of `stop_file`
    (so another terminal can pause a running sweep with `touch <stop_file>`). The run loop checks
    `should_stop()` at each boundary and breaks cleanly; every finished run is already recorded, so
    nothing is lost and `--resume` continues. A second Ctrl-C aborts immediately."""

    def __init__(self, stop_file: str | None = None):
        self.stop_file = stop_file
        self._stop = False
        self._orig = {}

    def _handler(self, signum, frame):
        if self._stop:                      # second signal -> hard abort
            raise KeyboardInterrupt
        self._stop = True
        print("\n[stop] requested — finishing the current run, then saving and stopping "
              "(Ctrl-C again to abort now)...", flush=True)

    def install(self) -> "StopController":
        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                self._orig[s] = signal.signal(s, self._handler)
            except (ValueError, OSError):   # e.g. not on the main thread
                pass
        return self

    def restore(self) -> None:
        for s, h in self._orig.items():
            try:
                signal.signal(s, h)
            except (ValueError, OSError):
                pass

    def should_stop(self) -> bool:
        if self._stop:
            return True
        if self.stop_file and os.path.exists(self.stop_file):
            self._stop = True
            print(f"\n[stop] stop-file seen ({os.path.basename(self.stop_file)}) — "
                  "saving and stopping after the current run.", flush=True)
            return True
        return False

    def clear_stop_file(self) -> None:
        """Remove the stop-file once honored, so a later --resume run is not stopped immediately."""
        if self.stop_file and os.path.exists(self.stop_file):
            try:
                os.remove(self.stop_file)
            except OSError:
                pass


def _parse_time(s: str) -> datetime.time:
    h, m = s.strip().split(":")
    return datetime.time(int(h), int(m))


class WindowGate:
    """An allowed clock window. `spec` is 'HH:MM-HH:MM' (local time) or None for always-open;
    a start later than the end wraps past midnight (e.g. 23:00-06:00)."""

    def __init__(self, spec: str | None):
        self.spec = spec
        self.start = self.end = None
        if spec:
            a, b = spec.split("-")
            self.start, self.end = _parse_time(a), _parse_time(b)

    def is_open(self, now: datetime.time | None = None) -> bool:
        if not self.spec:
            return True
        now = now or datetime.datetime.now().time()
        if self.start <= self.end:
            return self.start <= now <= self.end
        return now >= self.start or now <= self.end   # wraps midnight

    def wait_until_open(self, log=print, check_every: int = 60,
                        on_pause=None, on_resume=None) -> None:
        """Block until inside the window. `on_pause` runs once when the pause begins (e.g. stop the
        model server to free the GPU) and `on_resume` once when it ends (e.g. restart it); hook
        failures are logged, not fatal."""
        if self.is_open():
            return
        log(f"[window] outside {self.spec}; pausing until it opens "
            f"(now {datetime.datetime.now().strftime('%H:%M')})")
        _safe_hook(on_pause, "on-pause", log)
        while not self.is_open():
            time.sleep(check_every)
        log(f"[window] inside {self.spec}; resuming")
        _safe_hook(on_resume, "on-resume", log)


def _safe_hook(hook, name, log):
    if hook is None:
        return
    try:
        hook()
    except Exception as e:
        log(f"[window] {name} hook failed: {type(e).__name__}: {e}")
