"""docextract_core imports the standard library only, and adds no network, clock or subprocess use.

Gate 5 of hub Turn P2a. The clock (``time``, for ``ingested_at``) and ``subprocess`` (for
``git_revision``) already existed; the test pins them to the one module each lives in, so a new
use -- or a stray non-stdlib import -- fails loudly.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import docextract_core

PKG = Path(docextract_core.__file__).resolve().parent

#: Modules that can reach the network (or a local socket). None may be imported.
NETWORK = frozenset(
    {
        "asyncio",
        "ftplib",
        "http",
        "httpx",
        "requests",
        "aiohttp",
        "smtplib",
        "socket",
        "ssl",
        "telnetlib",
        "urllib",
        "xmlrpc",
    }
)


def _import_roots(path: Path) -> set[str]:
    """Top-level names imported by one module (absolute imports only; ``.rel`` is skipped)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _imports() -> dict[str, set[str]]:
    return {path.name: _import_roots(path) for path in PKG.glob("*.py")}


def test_only_standard_library_imports():
    standard = set(sys.stdlib_module_names)
    for name, roots in _imports().items():
        assert roots <= standard, f"{name} imports non-stdlib modules: {sorted(roots - standard)}"


def test_no_network_module_is_imported():
    for name, roots in _imports().items():
        assert not (roots & NETWORK), f"{name} imports network modules: {sorted(roots & NETWORK)}"


def test_the_clock_and_subprocess_stay_where_they_already_were():
    by_module = _imports()
    clock = {name for name, roots in by_module.items() if "time" in roots}
    subprocess = {name for name, roots in by_module.items() if "subprocess" in roots}
    assert clock == {"archive.py"}, f"a new clock use appeared in {sorted(clock)}"
    assert subprocess == {"__init__.py"}, f"a new subprocess use appeared in {sorted(subprocess)}"
