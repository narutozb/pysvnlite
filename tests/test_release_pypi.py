from __future__ import annotations

import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
from packaging.version import Version

import scripts.release_pypi as release_module
from scripts.release_pypi import (
    ProjectMetadata,
    ReleaseArtifact,
    ReleaseError,
    build_upload_command,
    collect_release_artifacts,
    ensure_published_annotated_tag,
    read_project_metadata,
    remove_existing_release_artifacts,
    validate_artifact_contents,
    validate_pypi_guard,
)


def test_read_project_metadata() -> None:
    metadata = read_project_metadata(Path("pyproject.toml"))

    assert metadata.name == release_module.PACKAGE
    assert metadata.version == Version("0.2.2")


def test_build_targets_pin_twine_compatible_core_metadata() -> None:
    with Path("pyproject.toml").open("rb") as file_obj:
        pyproject = release_module.tomllib.load(file_obj)

    targets = pyproject["tool"]["hatch"]["build"]["targets"]
    assert targets["wheel"]["core-metadata-version"] == "2.4"
    assert targets["sdist"]["core-metadata-version"] == "2.4"


def test_read_project_metadata_rejects_invalid_version(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        '[project]\nname = "pysvnlite"\nversion = "not a version"\n',
        encoding="utf-8",
    )

    with pytest.raises(ReleaseError, match="Invalid \\[project\\]\\.version"):
        read_project_metadata(pyproject_path)


def test_collect_release_artifacts_uses_only_current_project_version(
    tmp_path: Path,
) -> None:
    metadata = ProjectMetadata("pysvnlite", Version("0.1.5"))
    expected_names = {
        "pysvnlite-0.1.5-py3-none-any.whl",
        "pysvnlite-0.1.5.tar.gz",
    }
    for filename in expected_names | {
        "pysvnlite-0.1.4-py3-none-any.whl",
        "another_package-0.1.5.tar.gz",
        "README.txt",
    }:
        (tmp_path / filename).write_bytes(b"artifact")

    artifacts = collect_release_artifacts(tmp_path, metadata)

    assert {artifact.path.name for artifact in artifacts} == expected_names
    assert {artifact.kind for artifact in artifacts} == {"wheel", "sdist"}


def test_collect_release_artifacts_requires_wheel_and_sdist(tmp_path: Path) -> None:
    metadata = ProjectMetadata("pysvnlite", Version("0.1.5"))
    (tmp_path / "pysvnlite-0.1.5-py3-none-any.whl").write_bytes(b"wheel")

    with pytest.raises(ReleaseError, match="both wheel and sdist"):
        collect_release_artifacts(tmp_path, metadata)


def test_remove_existing_release_artifacts_preserves_other_versions(
    tmp_path: Path,
) -> None:
    metadata = ProjectMetadata("pysvnlite", Version("0.1.5"))
    current = tmp_path / "pysvnlite-0.1.5.tar.gz"
    previous = tmp_path / "pysvnlite-0.1.4.tar.gz"
    current.write_bytes(b"current")
    previous.write_bytes(b"previous")

    remove_existing_release_artifacts(tmp_path, metadata)

    assert not current.exists()
    assert previous.exists()


def _add_tar_file(
    archive: tarfile.TarFile,
    name: str,
    content: bytes = b"content",
) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    archive.addfile(info, io.BytesIO(content))


def _create_valid_artifacts(tmp_path: Path) -> list[ReleaseArtifact]:
    package = release_module.PACKAGE
    wheel_path = tmp_path / f"{package}-0.1.5-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, mode="w") as archive:
        archive.writestr(f"{package}/__init__.py", "")
        archive.writestr(f"{package}/py.typed", "")
        metadata = f"Metadata-Version: 2.4\nName: {package}\nVersion: 0.1.5\n"
        if release_module.RUNTIME_DEPENDENCY:
            metadata += "Requires-Dist: " + "".join(release_module.RUNTIME_DEPENDENCY) + "\n"
        archive.writestr(f"{package}-0.1.5.dist-info/METADATA", metadata)
        if release_module.CONSOLE_ENTRY:
            name, entry = release_module.CONSOLE_ENTRY
            archive.writestr(
                f"{package}-0.1.5.dist-info/entry_points.txt",
                f"[console_scripts]\n{name} = {entry}\n",
            )

    sdist_path = tmp_path / f"{package}-0.1.5.tar.gz"
    root = f"{package}-0.1.5"
    with tarfile.open(sdist_path, mode="w:gz") as archive:
        for relative_path in (
            f"src/{package}/__init__.py",
            f"src/{package}/py.typed",
            "pyproject.toml",
            "README.md",
            "LICENSE",
        ):
            _add_tar_file(archive, f"{root}/{relative_path}")

    return [
        ReleaseArtifact(wheel_path, "wheel"),
        ReleaseArtifact(sdist_path, "sdist"),
    ]


def test_validate_artifact_contents_accepts_expected_layout(tmp_path: Path) -> None:
    validate_artifact_contents(_create_valid_artifacts(tmp_path))


def test_validate_artifact_contents_rejects_missing_package(tmp_path: Path) -> None:
    artifacts = _create_valid_artifacts(tmp_path)
    wheel_path = artifacts[0].path
    with zipfile.ZipFile(wheel_path, mode="w") as archive:
        archive.writestr(f"{release_module.PACKAGE}/other.py", "")

    with pytest.raises(ReleaseError, match="missing required files"):
        validate_artifact_contents(artifacts)


@pytest.mark.parametrize(
    "member", ["AGENTS.md", ".agents/skills/SKILL.md", "other_package/__init__.py", "../secret"]
)
@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_validate_artifact_contents_rejects_unexpected_files(tmp_path, member, kind):
    artifacts = _create_valid_artifacts(tmp_path)
    if kind == "wheel":
        with zipfile.ZipFile(artifacts[0].path, "a") as archive:
            archive.writestr(member, "")
    else:
        with tarfile.open(artifacts[1].path, "w:gz") as archive:
            _add_tar_file(archive, f"{release_module.PACKAGE}-0.1.5/{member}")
    with pytest.raises(ReleaseError, match="archive member"):
        validate_artifact_contents(artifacts)


def test_production_upload_requires_confirmation_and_tag() -> None:
    metadata = ProjectMetadata("pysvnlite", Version("0.1.5"))

    with pytest.raises(ReleaseError, match="--confirm-version 0.1.5"):
        validate_pypi_guard(
            "pypi",
            metadata,
            None,
            {"v0.1.5"},
            allow_dirty=False,
            skip_checks=False,
        )

    with pytest.raises(ReleaseError, match="HEAD must have tag"):
        validate_pypi_guard(
            "pypi",
            metadata,
            "0.1.5",
            set(),
            allow_dirty=False,
            skip_checks=False,
        )

    assert (
        validate_pypi_guard(
            "pypi",
            metadata,
            "0.1.5",
            {"v0.1.5"},
            allow_dirty=False,
            skip_checks=False,
        )
        == "v0.1.5"
    )
    assert (
        validate_pypi_guard(
            "testpypi",
            metadata,
            None,
            set(),
            allow_dirty=True,
            skip_checks=True,
        )
        is None
    )


@pytest.mark.parametrize(
    ("allow_dirty", "skip_checks"),
    [
        (True, False),
        (False, True),
        (True, True),
    ],
)
def test_production_upload_rejects_safety_overrides(
    allow_dirty: bool,
    skip_checks: bool,
) -> None:
    metadata = ProjectMetadata("pysvnlite", Version("0.1.5"))

    with pytest.raises(ReleaseError, match="forbids release-safety overrides"):
        validate_pypi_guard(
            "pypi",
            metadata,
            "0.1.5",
            {"v0.1.5"},
            allow_dirty=allow_dirty,
            skip_checks=skip_checks,
        )


def test_published_annotated_tag_matches_remote(monkeypatch) -> None:
    tag_ref = "refs/tags/v0.1.5"
    responses = {
        ("git", "cat-file", "-t", tag_ref): "tag",
        ("git", "rev-parse", "HEAD"): "commit-sha",
        ("git", "rev-parse", tag_ref): "tag-object-sha",
        ("git", "rev-parse", f"{tag_ref}^{{}}"): "commit-sha",
        (
            "git",
            "ls-remote",
            "--tags",
            "origin",
            tag_ref,
            f"{tag_ref}^{{}}",
        ): (f"tag-object-sha\t{tag_ref}\ncommit-sha\t{tag_ref}^{{}}\n"),
    }

    def fake_capture(command, cwd=release_module.PROJECT_ROOT, env=None):
        return responses[tuple(command)]

    monkeypatch.setattr(release_module, "capture_command", fake_capture)

    ensure_published_annotated_tag("v0.1.5", "origin")


def test_published_tag_rejects_lightweight_tag(monkeypatch) -> None:
    monkeypatch.setattr(
        release_module,
        "capture_command",
        lambda command, cwd=release_module.PROJECT_ROOT, env=None: "commit",
    )

    with pytest.raises(ReleaseError, match="annotated Git tag"):
        ensure_published_annotated_tag("v0.1.5", "origin")


def test_published_tag_rejects_unpushed_tag(monkeypatch) -> None:
    tag_ref = "refs/tags/v0.1.5"
    responses = {
        ("git", "cat-file", "-t", tag_ref): "tag",
        ("git", "rev-parse", "HEAD"): "commit-sha",
        ("git", "rev-parse", tag_ref): "tag-object-sha",
        ("git", "rev-parse", f"{tag_ref}^{{}}"): "commit-sha",
        (
            "git",
            "ls-remote",
            "--tags",
            "origin",
            tag_ref,
            f"{tag_ref}^{{}}",
        ): "",
    }

    def fake_capture(command, cwd=release_module.PROJECT_ROOT, env=None):
        return responses[tuple(command)]

    monkeypatch.setattr(release_module, "capture_command", fake_capture)

    with pytest.raises(ReleaseError, match="has not been pushed unchanged"):
        ensure_published_annotated_tag("v0.1.5", "origin")


def test_build_upload_command_is_explicit_and_non_interactive(tmp_path: Path) -> None:
    artifacts = [
        ReleaseArtifact(tmp_path / "pysvnlite-0.1.5.tar.gz", "sdist"),
        ReleaseArtifact(
            tmp_path / "pysvnlite-0.1.5-py3-none-any.whl",
            "wheel",
        ),
    ]

    command = build_upload_command("testpypi", artifacts, True)

    assert command[:6] == [
        sys.executable,
        "-m",
        "twine",
        "upload",
        "--repository",
        "testpypi",
    ]
    assert "--non-interactive" in command
    assert command[-2:] == [str(artifact.path) for artifact in artifacts]
