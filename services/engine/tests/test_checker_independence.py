"""The checker must not share code with the scheduler (CLAUDE.md hard rule 3, BRIEF section 11).

Two independent proofs: a static scan of every import in the checker's source (only the
standard library and the checker itself are allowed), and a fresh interpreter that imports
every checker module and then looks at what got loaded.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import brimline_engine.checker

CHECKER = Path(brimline_engine.checker.__file__).parent
OWN = "brimline_engine.checker"


def bad_imports(source: str) -> list[str]:
    """Imports that are neither the standard library nor the checker's own modules."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            bad.append(f"relative import (level {node.level}) of {node.module}")
            continue
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            own = name == OWN or name.startswith(OWN + ".")
            if not own and name.split(".")[0] not in sys.stdlib_module_names:
                bad.append(name)
    # Dynamic imports would dodge the scan above.
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = (
                f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            )
            if name in {"__import__", "import_module"}:
                bad.append(f"dynamic import via {name}")
    return bad


def checker_files() -> list[Path]:
    files = sorted(CHECKER.rglob("*.py"))
    assert len(files) >= 5, files  # the scan must actually be looking at the checker
    return files


@pytest.mark.parametrize("path", checker_files(), ids=lambda p: p.name)
def test_checker_source_imports_only_stdlib_and_itself(path: Path) -> None:
    assert bad_imports(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "line",
    [
        "from brimline_engine.scheduling.durations import task_durations",
        "import brimline_engine.scheduling",
        "from brimline_engine import shop_config",
        "from ..scheduling import model",
        "import pydantic",
        "import importlib\nimportlib.import_module('brimline_engine.scheduling')",
        "__import__('brimline_engine.scheduling')",
    ],
)
def test_the_scan_catches_a_planted_import(line: str) -> None:
    assert bad_imports(line) != []


def test_the_scan_allows_what_the_checker_needs() -> None:
    assert bad_imports("import json\nfrom brimline_engine.checker.rules import Rules") == []


def test_importing_the_checker_loads_no_scheduler_module() -> None:
    modules = ["brimline_engine.checker." + p.stem for p in checker_files() if p.stem != "__init__"]
    code = (
        "import sys\n"
        + "".join(f"import {m}\n" for m in modules)
        + "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('brimline_engine')"
        " or m.split('.')[0] in {'pydantic', 'ortools', 'fastapi'})))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.split()
    assert "brimline_engine.checker.check" in out  # it really imported the checker
    assert [m for m in out if not (m == "brimline_engine" or m.startswith(OWN))] == []
