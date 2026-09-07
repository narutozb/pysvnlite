#!/usr/bin/env python3
"""Build, validate, and optionally upload pysvnlite releases to PyPI."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import importlib.util
import os
import shlex
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from email.parser import BytesParser
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "pysvnlite"
CONSOLE_ENTRY: Optional[tuple[str, str]] = None
RUNTIME_DEPENDENCY: Optional[tuple[str, str]] = None


class ReleaseError(RuntimeError):
    """A release precondition or artifact validation failed."""


@dataclass(frozen=True)
class ProjectMetadata:
    name: str
    version: Version


@dataclass(frozen=True)
class ReleaseArtifact:
    path: Path
    kind: str


def read_project_metadata(pyproject_path: Path) -> ProjectMetadata:
    try:
        with pyproject_path.open("rb") as file_obj:
            data = tomllib.load(file_obj)
        project = data["project"]
        name = project["name"]
        version = project["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseError(f"Cannot read project metadata from {pyproject_path}: {exc}") from exc

    if not isinstance(name, str) or not isinstance(version, str):
        raise ReleaseError("[project].name and [project].version must be strings")
    try:
        parsed_version = Version(version)
    except InvalidVersion as exc:
        raise ReleaseError(f"Invalid [project].version {version!r}") from exc
    return ProjectMetadata(name=name, version=parsed_version)


def _artifact_identity(path: Path) -> Optional[tuple[str, Version, str]]:
    try:
        if path.name.endswith(".whl"):
            name, version, _, _ = parse_wheel_filename(path.name)
            return canonicalize_name(name), version, "wheel"
        if path.name.endswith((".tar.gz", ".zip")):
            name, version = parse_sdist_filename(path.name)
            return canonicalize_name(name), version, "sdist"
    except (InvalidWheelFilename, InvalidSdistFilename):
        return None
    return None


def collect_release_artifacts(
    dist_dir: Path,
    metadata: ProjectMetadata,
) -> list[ReleaseArtifact]:
    expected_name = canonicalize_name(metadata.name)
    artifacts: list[ReleaseArtifact] = []
    if not dist_dir.is_dir():
        raise ReleaseError(f"Distribution directory does not exist: {dist_dir}")

    for path in sorted(dist_dir.iterdir()):
        if not path.is_file():
            continue
        identity = _artifact_identity(path)
        if identity is None:
            continue
        name, version, kind = identity
        if name == expected_name and version == metadata.version:
            artifacts.append(ReleaseArtifact(path=path, kind=kind))

    kinds = {artifact.kind for artifact in artifacts}
    if "wheel" not in kinds or "sdist" not in kinds:
        raise ReleaseError(
            f"Expected both wheel and sdist for {metadata.name} {metadata.version} in {dist_dir}"
        )
    return artifacts


def _missing_archive_members(
    names: set[str],
    required_suffixes: Sequence[str],
) -> list[str]:
    return [
        suffix
        for suffix in required_suffixes
        if not any(name == suffix or name.endswith(f"/{suffix}") for name in names)
    ]


def _validate_archive_scope(names: set[str], path: Path, kind: str) -> None:
    for name in names:
        parts = PurePosixPath(name).parts
        if not parts or name.startswith("/") or ".." in parts or "\\" in name:
            raise ReleaseError(f"Unsafe archive member in {path.name}: {name}")
        if kind == "wheel":
            allowed = (
                parts[0] == PACKAGE
                or parts[0].startswith(f"{PACKAGE}-")
                and parts[0].endswith(".dist-info")
            )
        else:
            content = parts[1:]
            allowed = (
                not content
                or content
                in [
                    ("LICENSE",),
                    ("README.md",),
                    ("pyproject.toml",),
                    ("PKG-INFO",),
                    ("src",),
                    (".gitignore",),
                ]
                or content[:2] == ("src", PACKAGE)
            )
        if (
            not allowed
            or set(parts)
            & {"__pycache__", ".agents", ".codex", ".github", ".vscode", "AGENTS.md", "SKILL.md"}
            or name.endswith((".pyc", "/AGENTS.md", "/SKILL.md"))
        ):
            raise ReleaseError(f"Unexpected archive member in {path.name}: {name}")


def _validate_wheel_contents(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            _validate_archive_scope(names, path, "wheel")
            missing = _missing_archive_members(
                names,
                (
                    f"{PACKAGE}/__init__.py",
                    f"{PACKAGE}/py.typed",
                ),
            )
            if missing:
                raise ReleaseError(
                    f"Wheel {path.name} is missing required files: {', '.join(missing)}"
                )

            metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metadata_files) != 1:
                raise ReleaseError("Wheel must contain exactly one METADATA file")
            wheel_metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
            if RUNTIME_DEPENDENCY is not None:
                dep_name, specifier = RUNTIME_DEPENDENCY
                dependencies = [
                    Requirement(value) for value in wheel_metadata.get_all("Requires-Dist", [])
                ]
                if not any(
                    canonicalize_name(dep.name) == dep_name
                    and dep.specifier == SpecifierSet(specifier)
                    and dep.marker is None
                    for dep in dependencies
                ):
                    raise ReleaseError(f"Wheel must depend on {dep_name}{specifier}")
            entry_point_files = [
                name for name in names if name.endswith(".dist-info/entry_points.txt")
            ]
            if CONSOLE_ENTRY is None:
                if entry_point_files:
                    raise ReleaseError("Library wheel must not contain console entry points")
                return
            if len(entry_point_files) != 1:
                raise ReleaseError(f"Wheel {path.name} must contain exactly one entry_points.txt")
            entry_points = configparser.ConfigParser(interpolation=None)
            entry_points.read_string(archive.read(entry_point_files[0]).decode("utf-8"))
    except (
        OSError,
        UnicodeDecodeError,
        configparser.Error,
        zipfile.BadZipFile,
    ) as exc:
        raise ReleaseError(f"Cannot inspect wheel {path}: {exc}") from exc

    console_entry = entry_points.get(
        "console_scripts",
        CONSOLE_ENTRY[0],
        fallback="",
    ).strip()
    if console_entry != CONSOLE_ENTRY[1]:
        raise ReleaseError(
            f"Wheel {path.name} has invalid pysvnlite console entry point: "
            f"{console_entry or '<missing>'}"
        )


def _validate_sdist_contents(path: Path) -> None:
    try:
        if path.name.endswith(".tar.gz"):
            with tarfile.open(path, mode="r:gz") as archive:
                names = set(archive.getnames())
        else:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise ReleaseError(f"Cannot inspect sdist {path}: {exc}") from exc

    _validate_archive_scope(names, path, "sdist")
    missing = _missing_archive_members(
        names,
        (
            f"src/{PACKAGE}/__init__.py",
            f"src/{PACKAGE}/py.typed",
            "pyproject.toml",
            "README.md",
            "LICENSE",
        ),
    )
    if missing:
        raise ReleaseError(f"Sdist {path.name} is missing required files: {', '.join(missing)}")


def validate_artifact_contents(
    artifacts: Sequence[ReleaseArtifact],
) -> None:
    for artifact in artifacts:
        if artifact.kind == "wheel":
            _validate_wheel_contents(artifact.path)
        elif artifact.kind == "sdist":
            _validate_sdist_contents(artifact.path)
        else:
            raise ReleaseError(f"Unknown artifact kind: {artifact.kind}")


def smoke_test_wheels(
    artifacts: Sequence[ReleaseArtifact],
    metadata: ProjectMetadata,
) -> None:
    smoke_code = (
        "import sys; "
        "sys.path.insert(0, sys.argv[1]); "
        "from importlib import import_module, metadata; "
        "from pathlib import Path; "
        f"package = import_module('{PACKAGE}'); "
        f"assert metadata.version('{PACKAGE}') == sys.argv[2]; "
        "assert Path(package.__file__).is_relative_to(Path(sys.argv[1])); "
    )
    if CONSOLE_ENTRY is not None:
        smoke_code += f"import_module('{CONSOLE_ENTRY[1].split(':')[0]}'); "
    if RUNTIME_DEPENDENCY is not None:
        smoke_code += f"dependency = import_module('{RUNTIME_DEPENDENCY[0]}'); assert Path(dependency.__file__).is_relative_to(Path(sys.argv[1])); "
    for artifact in artifacts:
        if artifact.kind != "wheel":
            continue
        with tempfile.TemporaryDirectory(prefix="pysvnlite-wheel-smoke-") as temp_dir:
            run_command(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--target",
                    temp_dir,
                    str(artifact.path),
                ]
            )
            run_command(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    smoke_code,
                    temp_dir,
                    str(metadata.version),
                ]
            )


def remove_existing_release_artifacts(
    dist_dir: Path,
    metadata: ProjectMetadata,
) -> None:
    if not dist_dir.exists():
        dist_dir.mkdir(parents=True)
        return
    if not dist_dir.is_dir():
        raise ReleaseError(f"Distribution path is not a directory: {dist_dir}")

    expected_name = canonicalize_name(metadata.name)
    for path in dist_dir.iterdir():
        if not path.is_file():
            continue
        identity = _artifact_identity(path)
        if identity is None:
            continue
        name, version, _ = identity
        if name == expected_name and version == metadata.version:
            path.unlink()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_command(command: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(list(command))
    return shlex.join(command)


def run_command(command: Sequence[str], cwd: Path = PROJECT_ROOT) -> None:
    print(f"$ {format_command(command)}", flush=True)
    subprocess.run(list(command), cwd=cwd, check=True)


def capture_command(
    command: Sequence[str],
    cwd: Path = PROJECT_ROOT,
    env: Optional[dict[str, str]] = None,
) -> str:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def ensure_release_tools() -> None:
    missing = [name for name in ("build", "twine") if importlib.util.find_spec(name) is None]
    if missing:
        raise ReleaseError(
            "Missing release tools: "
            + ", ".join(missing)
            + '. Install them with: python -m pip install -e ".[release]"'
        )


def ensure_clean_worktree() -> None:
    status = capture_command(["git", "status", "--porcelain", "--untracked-files=all"])
    if status:
        raise ReleaseError(
            "Git worktree is not clean. Commit/stash changes, or use "
            "--allow-dirty only for local/TestPyPI validation."
        )


def tags_at_head() -> set[str]:
    output = capture_command(["git", "tag", "--points-at", "HEAD"])
    return {line.strip() for line in output.splitlines() if line.strip()}


def validate_pypi_guard(
    repository: str,
    metadata: ProjectMetadata,
    confirm_version: Optional[str],
    tags: set[str],
    *,
    allow_dirty: bool,
    skip_checks: bool,
) -> Optional[str]:
    if repository != "pypi":
        return None
    unsafe_options = [
        option
        for option, enabled in (
            ("--allow-dirty", allow_dirty),
            ("--skip-checks", skip_checks),
        )
        if enabled
    ]
    if unsafe_options:
        raise ReleaseError(
            "Production PyPI upload forbids release-safety overrides: " + ", ".join(unsafe_options)
        )
    expected_version = str(metadata.version)
    if confirm_version != expected_version:
        raise ReleaseError(f"Production PyPI upload requires --confirm-version {expected_version}")
    for expected_tag in (f"v{expected_version}", expected_version):
        if expected_tag in tags:
            return expected_tag
    raise ReleaseError(
        f"HEAD must have tag v{expected_version} (or {expected_version}); "
        "create an annotated tag and push it before publishing."
    )


def ensure_published_annotated_tag(
    tag: str,
    remote: str,
) -> None:
    tag_ref = f"refs/tags/{tag}"
    object_type = capture_command(["git", "cat-file", "-t", tag_ref])
    if object_type != "tag":
        raise ReleaseError(f"Production tag {tag!r} must be an annotated Git tag.")

    head_commit = capture_command(["git", "rev-parse", "HEAD"])
    local_tag_object = capture_command(["git", "rev-parse", tag_ref])
    local_tag_commit = capture_command(["git", "rev-parse", f"{tag_ref}^{{}}"])
    if local_tag_commit != head_commit:
        raise ReleaseError(f"Production tag {tag!r} does not resolve to the current commit.")

    git_env = os.environ.copy()
    git_env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        remote_output = capture_command(
            [
                "git",
                "ls-remote",
                "--tags",
                remote,
                tag_ref,
                f"{tag_ref}^{{}}",
            ],
            env=git_env,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ReleaseError(
            f"Cannot verify production tag on Git remote {remote!r}: "
            f"{detail or 'git ls-remote failed'}"
        ) from exc

    remote_refs = {}
    for line in remote_output.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            remote_refs[parts[1]] = parts[0]

    if remote_refs.get(tag_ref) != local_tag_object:
        raise ReleaseError(
            f"Annotated tag {tag!r} has not been pushed unchanged to Git remote {remote!r}."
        )
    if remote_refs.get(f"{tag_ref}^{{}}") != head_commit:
        raise ReleaseError(f"Remote tag {tag!r} does not resolve to the current commit.")


def build_upload_command(
    repository: str,
    artifacts: Sequence[ReleaseArtifact],
    non_interactive: bool,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "twine",
        "upload",
        "--repository",
        repository,
    ]
    if non_interactive:
        command.append("--non-interactive")
    command.extend(str(artifact.path) for artifact in artifacts)
    return command


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build, validate, and optionally upload pysvnlite to PyPI.",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload validated artifacts; without this flag the script only prepares them.",
    )
    parser.add_argument(
        "--repository",
        choices=("testpypi", "pypi"),
        default="testpypi",
        help="Twine repository (default: testpypi).",
    )
    parser.add_argument(
        "--confirm-version",
        help="Required for production PyPI upload; must equal [project].version.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Pass --non-interactive to Twine for CI use.",
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip Ruff, mypy, and pytest for local/TestPyPI troubleshooting.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow local or TestPyPI builds from an uncommitted worktree.",
    )
    parser.add_argument(
        "--git-remote",
        default="origin",
        help="Git remote that must contain the production tag (default: origin).",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=Path("dist"),
        help="Distribution output directory relative to the repository root.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        metadata = read_project_metadata(PROJECT_ROOT / "pyproject.toml")
        ensure_release_tools()
        if not args.allow_dirty:
            ensure_clean_worktree()

        if args.upload:
            release_tag = validate_pypi_guard(
                args.repository,
                metadata,
                args.confirm_version,
                tags_at_head() if args.repository == "pypi" else set(),
                allow_dirty=args.allow_dirty,
                skip_checks=args.skip_checks,
            )
            if release_tag is not None:
                ensure_published_annotated_tag(
                    release_tag,
                    args.git_remote,
                )

        if not args.skip_checks:
            run_command([sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"])
            run_command([sys.executable, "-m", "mypy", "src", "scripts"])
            run_command([sys.executable, "-m", "pytest", "-q"])

        dist_dir = args.dist_dir
        if not dist_dir.is_absolute():
            dist_dir = PROJECT_ROOT / dist_dir
        dist_dir = dist_dir.resolve()
        remove_existing_release_artifacts(dist_dir, metadata)
        run_command([sys.executable, "-m", "build", "--outdir", str(dist_dir)])

        artifacts = collect_release_artifacts(dist_dir, metadata)
        validate_artifact_contents(artifacts)
        run_command(
            [sys.executable, "-m", "twine", "check"]
            + [str(artifact.path) for artifact in artifacts]
        )
        smoke_test_wheels(artifacts, metadata)

        print(f"Prepared {metadata.name} {metadata.version}:")
        for artifact in artifacts:
            print(f"  {hash_file(artifact.path)}  {artifact.path}")

        if not args.upload:
            print("Upload not requested. Re-run with --upload after reviewing the artifacts.")
            return 0

        run_command(
            build_upload_command(
                args.repository,
                artifacts,
                args.non_interactive,
            )
        )
        print(f"Uploaded {metadata.name} {metadata.version} to {args.repository}.")
        return 0
    except ReleaseError as exc:
        print(f"release error: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(
            f"command failed with exit code {exc.returncode}: {format_command(exc.cmd)}",
            file=sys.stderr,
        )
        return exc.returncode or 1
    except OSError as exc:
        print(f"release error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("release cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
