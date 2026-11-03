"""How the package hangs together: imports run one way, only the providers know
the drivers, and sync code doesn't depend on async code."""

import ast
import graphlib
from collections.abc import Iterator
from pathlib import Path

import quma

ROOT = Path(quma.__file__).parent
DRIVERS = {"aiosqlite", "asyncmy", "MySQLdb", "psycopg", "psycopg2", "sqlite3"}


def modules() -> dict[str, Path]:
    found = {}
    for path in ROOT.rglob("*.py"):
        parts = path.relative_to(ROOT).with_suffix("").parts
        if parts[0] != "tests":
            found[".".join(("quma", *parts)).removesuffix(".__init__")] = path
    return found


def run_time_nodes(tree: ast.AST) -> Iterator[ast.AST]:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
            yield from (
                inner
                for branch in node.orelse
                for inner in (branch, *run_time_nodes(branch))
            )
            continue
        yield node
        yield from run_time_nodes(node)


def imports(name: str, path: Path) -> set[str]:
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    found: set[str] = set()
    for node in run_time_nodes(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                parts = parts[: len(parts) - node.level + 1]
                base = ".".join(parts + ([base] if base else []))
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def internal(name: str, path: Path, names: dict[str, Path]) -> set[str]:
    found = set()
    for imported in imports(name, path):
        parent = imported.rpartition(".")[0]
        found.add(imported if imported in names else parent)
    return found & set(names) - {name}


def test_imports_run_one_way():
    names = modules()
    graph = {name: internal(name, path, names) for name, path in names.items()}
    graphlib.TopologicalSorter(graph).prepare()


def test_only_providers_import_drivers():
    for name, path in modules().items():
        if not name.startswith("quma.provider"):
            used = {found.partition(".")[0] for found in imports(name, path)}
            assert not used & DRIVERS, name


def test_sync_modules_do_not_import_async_ones():
    names = modules()
    for name, path in names.items():
        if name != "quma" and not name.startswith("quma.aio"):
            assert not {
                found
                for found in internal(name, path, names)
                if found.startswith("quma.aio")
            }, name
