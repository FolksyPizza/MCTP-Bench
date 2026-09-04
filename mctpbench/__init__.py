"""ASTP-Bench — evaluation harness for ASTP.

Depends on the Core ASTP reference implementation. We locate it via ASTP_HOME (defaults to the
sibling repo, whether its folder is named `ASTP` or the legacy `MCTP`) and add its `core/` and
`bench/` dirs to sys.path so we can `import astp` and reuse shared scenarios.
"""
import os
import sys

_base = os.path.join(os.path.dirname(__file__), "..", "..")
_home = os.environ.get("ASTP_HOME") or next(
    (os.path.abspath(os.path.join(_base, n)) for n in ("ASTP", "MCTP")
     if os.path.isdir(os.path.join(_base, n))),
    os.path.abspath(os.path.join(_base, "ASTP")),
)
for _sub in ("core", "bench"):
    _p = os.path.abspath(os.path.join(_home, _sub))
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

ASTP_HOME = _home
