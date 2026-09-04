"""Shared helpers for backend contract tests."""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(autouse=True)
def _isolate_mypc_history(tmp_path, monkeypatch):
    """Redirect the mypc known-hosts history file into a per-test tmp dir.

    Route tests trigger save_known_host() hooks (probe / train start); this
    keeps those writes out of the real checkout.
    """
    import mypc_history

    monkeypatch.setattr(
        mypc_history, "_history_path",
        lambda: str(tmp_path / "mypc_known_hosts.json"),
    )


def collect_route_paths(routes, prefix=""):
    """Flatten an app's route table into a set of full path strings.

    FastAPI >= 0.141 includes routers lazily: ``app.routes`` then contains
    private ``_IncludedRouter`` entries (no ``.path``) instead of the
    eagerly flattened routes older versions produce. Walk both shapes via
    duck typing so these contract tests pass on either FastAPI generation.
    """
    paths = set()
    for route in routes:
        path = getattr(route, "path", None)
        if path is not None:
            paths.add(prefix + path)
            continue
        original_router = getattr(route, "original_router", None)
        if original_router is not None:  # FastAPI >= 0.141 lazy include
            include_prefix = getattr(route.include_context, "prefix", "")
            paths |= collect_route_paths(original_router.routes, prefix + include_prefix)
    return paths
