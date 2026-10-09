"""项目根 conftest：确保 pytest 能发现 src/ticket_diagnose/tests 下的用例，
并提前把两个源项目 src 与自身 src 加入 sys.path（供离线集成）。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_ROOT, "src")
_PROJECTS = os.path.dirname(_ROOT)

for p in [
    _SRC,
    os.path.join(_PROJECTS, "ticket-classifier", "src"),
    os.path.join(_PROJECTS, "parallel-code-reviewer", "src"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)