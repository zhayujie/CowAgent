"""Every outbound call a model backend makes has to be bounded.

A backend that calls ``requests.*`` with no timeout waits forever: the socket
stays open, nothing is raised and nothing is logged, so the turn never completes
and the user never gets a reply. That is the one failure mode a timeout exists
to prevent, and it is invisible from the outside -- the process looks healthy
and simply never answers.

The package already bounds almost every call (deepseek, moonshot, doubao,
minimax, mimo, modelscope, qianfan, gemini and linkai all pass ``timeout=`` to
at least one site). This scans the whole package instead of the backends that
happened to be fixed today, so a new backend, a new endpoint on an existing one,
or a rewritten call cannot quietly go without one.
"""

import ast
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"


def _outbound_calls():
    """Every ``requests.<verb>(...)`` under models/, as (path, node, verb).

    Only the module-level ``requests`` object is matched. That is what every
    backend uses -- nothing in the package builds a ``requests.Session``, which
    would carry its own default and need a different check.
    """
    for path in sorted(MODELS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            if (isinstance(called, ast.Attribute)
                    and isinstance(called.value, ast.Name)
                    and called.value.id == "requests"):
                yield path.relative_to(MODELS_DIR.parent), node, called.attr


def test_every_outbound_request_is_bounded():
    unbounded = [
        f"{path}:{node.lineno} requests.{verb}(...)"
        for path, node, verb in _outbound_calls()
        if not any(keyword.arg == "timeout" for keyword in node.keywords)
    ]

    assert unbounded == []


def test_the_scan_actually_covers_the_backends():
    """Without this, a scan that silently matched nothing -- a moved directory,
    a renamed import -- would make the test above pass by having nothing to
    check."""
    found = list(_outbound_calls())

    assert len(found) > 20
    assert {"post", "get"} <= {verb for _, _, verb in found}
