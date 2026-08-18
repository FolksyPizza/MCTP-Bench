"""MCTP-Bench — evaluation harness for MCTP.

Depends on the Core MCTP reference implementation. We locate it via MCTP_HOME (defaults to
the sibling `../MCTP` repo) and add its `core/` and `bench/` dirs to sys.path so we can
`import mctp` and reuse shared scenarios.
"""
import os
import sys

_home = os.environ.get(
    "MCTP_HOME",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "MCTP")),
)
for _sub in ("core", "bench"):
    _p = os.path.abspath(os.path.join(_home, _sub))
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

MCTP_HOME = _home
