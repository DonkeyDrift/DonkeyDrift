"""Shared helpers for backend contract tests."""


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
