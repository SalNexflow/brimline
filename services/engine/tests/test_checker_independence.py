"""The checker must not share code with the scheduler (CLAUDE.md hard rule 3, BRIEF section 11).

Two independent proofs: a static scan of every import in the checker's source (only the
standard library and the checker itself are allowed, and no way of loading code by name at run
time), and a fresh interpreter that imports every checker module, runs real checks and
mutations, and then looks at what got loaded.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

import brimline_engine.checker
from brimline_engine.scheduling.baselines import edd
from brimline_engine.scheduling.config import load_scheduler_config
from brimline_engine.scheduling.export import document
from brimline_engine.scheduling.generator import generate
from brimline_engine.shop_config import load_shop_config

CHECKER = Path(brimline_engine.checker.__file__).parent
OWN = "brimline_engine.checker"
# Standard-library ways to load code by name at run time, which an import scan cannot follow.
DYNAMIC_MODULES = {"importlib", "runpy", "imp", "pkgutil", "zipimport"}
DYNAMIC_CALLS = {"__import__", "import_module", "exec", "eval", "compile", "run_module", "run_path"}


def bad_imports(source: str) -> list[str]:
    """Imports that are neither the standard library nor the checker's own modules, and any
    way of loading code by name at run time."""
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
            top = name.split(".")[0]
            if not own and (top not in sys.stdlib_module_names or top in DYNAMIC_MODULES):
                bad.append(name)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = (
                f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            )
            if name in DYNAMIC_CALLS:
                bad.append(f"dynamic code via {name}")
        if isinstance(node, ast.Attribute) and node.attr == "modules":
            bad.append("sys.modules access")
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
        "from brimline_engine.dispatch.guard import check",  # M12: nor the dispatch agent's code
        "import brimline_engine.machines.fleet",
        "from brimline_engine import shop_config",
        "from ..scheduling import model",
        "import pydantic",
        "import importlib\nimportlib.import_module('brimline_engine.scheduling')",
        "__import__('brimline_engine.scheduling')",
        "import runpy\nrunpy.run_module('brimline_engine.scheduling.model')",
        "exec('import brimline_engine.scheduling')",
        "eval('1')",
        "import importlib.util\nimportlib.util.spec_from_file_location('m', 'model.py')",
        "import sys\nm = sys.modules['brimline_engine.scheduling.model']",
    ],
)
def test_the_scan_catches_a_planted_import(line: str) -> None:
    assert bad_imports(line) != []


def test_the_scan_allows_what_the_checker_needs() -> None:
    assert bad_imports("import json\nfrom brimline_engine.checker.rules import Rules") == []


def test_running_the_checker_loads_no_scheduler_module(tmp_path: Path) -> None:
    # A real plan is made here (this test may use the scheduler); a fresh interpreter that
    # imports only the checker then checks and mutates it, and lists what it loaded.
    cfg = load_scheduler_config()
    inst = generate(1, 20, load_shop_config(), cfg)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(document(inst, edd(inst, cfg.durations))), encoding="utf-8")
    modules = [OWN + "." + p.stem for p in checker_files() if p.stem != "__init__"]
    lines = [
        "import json, sys",
        *(f"import {m}" for m in modules),
        "from brimline_engine.checker import check_document, load_rules",
        "from brimline_engine.checker.mutations import mutants",
        f"doc = json.load(open({str(plan)!r}, encoding='utf-8'))",
        "assert check_document(doc).valid",
        "assert all(not check_document(m).valid for _, _, m in mutants(doc, load_rules(), 1, 1))",
        "names = [m for m in sys.modules if m.startswith('brimline_engine')",
        "         or m.split('.')[0] in {'pydantic', 'ortools', 'fastapi'}]",
        "print('\\n'.join(sorted(names)))",
    ]
    out = subprocess.run(
        [sys.executable, "-c", "\n".join(lines)], capture_output=True, text=True, check=True
    ).stdout.split()
    assert "brimline_engine.checker.check" in out  # it really ran the checker
    assert [m for m in out if not (m == "brimline_engine" or m.startswith(OWN))] == []
