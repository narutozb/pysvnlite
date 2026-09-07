# AGENTS.md

This repository owns only `src/pysvnlite`, extracted from svnpypi v0.1.7.
The svnpypi CLI lives at https://github.com/narutozb/svnpypi and consumes this
package as a published dependency. Do not reintroduce a CLI or vendored code.

- Preserve Python >=3.9, existing API signatures and MIT attribution.
- Use standard library facilities; avoid new runtime dependencies.
- Keep SVN commands non-interactive and use XML for metadata, bytes for content.
- Preserve structured SVNCommandError, credential redaction, atomic downloads,
  conflict guards, timeout and process-tree cleanup behavior.
- Test writes only against temporary local SVN repositories, never production.
- Keep filesystem postconditions: native exit code zero alone does not prove a
  checkout reached its intended destination. See docs/windows-paths.md.
- Never automatically rename or delete paths created incorrectly by a client.
- src/pysvnlite/repo.py owns command construction; runner.py owns subprocesses;
  parser_*.py and models.py own parsing and structured results.
- Tests use pytest; tests/conftest.py adds src to sys.path.
- Run `python -m ruff check src tests scripts`, `python -m mypy src scripts`,
  `python -m pytest -q` and `python scripts/release_pypi.py --allow-dirty`.
- Build with hatchling. Wheel/sdist include only this package, metadata, README
  and LICENSE; preserve py.typed and exclude agent/development files.
- Release via scripts/release_pypi.py. Production requires clean worktree,
  full checks and an annotated version tag pushed unchanged to origin.
- Never commit secrets or publish/tag without explicit user authorization.
- Update Chinese CHANGELOG and relevant docs for behavioral changes; state
  platform or authentication combinations that were not actually tested.
