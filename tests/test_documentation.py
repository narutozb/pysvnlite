from __future__ import annotations

import ast
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from scripts.release_pypi import read_project_metadata

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = sorted(
    [path for name in ("README.md", "CHANGELOG.md", "ROADMAP.md") if (path := ROOT / name).exists()]
    + list((ROOT / "docs").rglob("*.md"))
)
FENCES = re.compile(r"^```([^\n]*)\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
LINKS = re.compile(r"\[[^\]\n]+\]\(([^)\s]+)\)")


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: path.relative_to(ROOT).as_posix())
def test_documentation_links_exist(document: Path) -> None:
    content = FENCES.sub("", document.read_text(encoding="utf-8"))
    project = read_project_metadata(ROOT / "pyproject.toml").name
    own_prefix = f"https://github.com/narutozb/{project}/blob/main/"
    for match in LINKS.finditer(content):
        target = match.group(1).strip("<>")
        if target.startswith(own_prefix):
            path = ROOT / unquote(urlsplit(target).path.split("/blob/main/", 1)[1])
        else:
            url = urlsplit(target)
            if url.scheme or url.netloc or not url.path:
                continue
            path = document.parent / unquote(url.path)
        assert path.exists(), f"{document.relative_to(ROOT)}: missing link {target}"


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: path.relative_to(ROOT).as_posix())
def test_documentation_python_snippets_parse(document: Path) -> None:
    for block in FENCES.finditer(document.read_text(encoding="utf-8")):
        if block.group(1).strip() in {"python", "py"}:
            ast.parse(block.group(2), filename=str(document))


def test_readme_current_version_matches_metadata() -> None:
    version = read_project_metadata(ROOT / "pyproject.toml").version
    assert f"**{version}**" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_api_reference_signatures_match_source() -> None:
    source = ast.parse((ROOT / "src/pysvnlite/repo.py").read_text(encoding="utf-8"))
    repo = next(
        node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "SVNRepo"
    )
    reference = (ROOT / "docs/api-reference.md").read_text(encoding="utf-8")
    documented = {}
    for block in FENCES.finditer(reference):
        signature = block.group(2).strip()
        if block.group(1).strip() != "text" or "(" not in signature:
            continue
        function = ast.parse(f"def {signature}:\n    pass\n").body[0]
        assert isinstance(function, ast.FunctionDef)
        documented[function.name] = function

    expected = {}
    for node in repo.body:
        if isinstance(node, ast.FunctionDef) and (
            not node.name.startswith("_") or node.name == "__init__"
        ):
            node.args.args = [argument for argument in node.args.args if argument.arg != "self"]
            expected[node.name] = node
    assert documented.keys() == expected.keys()
    for name, node in expected.items():
        other = documented[name]
        assert ast.dump(node.args) == ast.dump(other.args), name
        assert (ast.dump(node.returns) if node.returns else None) == (
            ast.dump(other.returns) if other.returns else None
        ), name


def test_api_reference_covers_model_fields() -> None:
    source = ast.parse((ROOT / "src/pysvnlite/models.py").read_text(encoding="utf-8"))
    reference = (ROOT / "docs/api-reference.md").read_text(encoding="utf-8")
    for node in source.body:
        if not isinstance(node, ast.ClassDef):
            continue
        section = reference.split(f"### {node.name}\n", 1)
        assert len(section) == 2, f"Undocumented model: {node.name}"
        content = section[1].split("\n### ", 1)[0]
        for field in node.body:
            if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name):
                assert f"`{field.target.id}`" in content, f"{node.name}.{field.target.id}"
