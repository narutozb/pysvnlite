from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


_URL_USERINFO_RE = re.compile(
    r"(?i)([a-z][a-z0-9+.-]*://)([^/@\s]+)@"
)


def redact_url_credentials(text: str) -> str:
    """Hide URL userinfo before text is written to logs or records."""
    return _URL_USERINFO_RE.sub(r"\1***@", text)


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in patterns)


@dataclass
class SVNCommandError(RuntimeError):
    """
    在调用 svn 子进程时，如果返回码 != 0，用这个异常包装。
    """

    cmd: List[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def output_text(self) -> str:
        return f"{self.stderr}\n{self.stdout}"

    @property
    def is_path_not_found(self) -> bool:
        return self.is_local_repository_not_found or _contains_any(
            self.output_text,
            (
                "e160013",
                "e200009",
                "path not found",
                "file not found",
                "not found in repository",
                "non-existent in revision",
                "doesn't exist",
                "does not exist",
                "not a valid url",
                "could not list all targets because some targets don't exist",
            ),
        )

    @property
    def is_local_repository_not_found(self) -> bool:
        combined_text = "\n".join([*self.cmd, self.output_text]).lower()
        return "file://" in combined_text and _contains_any(
            self.output_text,
            (
                "e180001",
                "unable to open repository",
            ),
        )

    @property
    def is_authentication_error(self) -> bool:
        return _contains_any(
            self.output_text,
            (
                "e215004",
                "authentication failed",
                "could not authenticate",
                "authorization failed: could not authenticate",
                "no more credentials",
            ),
        )

    @property
    def is_authorization_error(self) -> bool:
        if self.is_authentication_error:
            return False
        return _contains_any(
            self.output_text,
            (
                "e170001",
                "authorization failed",
                "not authorized",
                "access denied",
                "forbidden",
                "permission denied",
            ),
        )

    @property
    def is_network_error(self) -> bool:
        return _contains_any(
            self.output_text,
            (
                "e000110",
                "e670002",
                "e730061",
                "unable to connect",
                "could not resolve hostname",
                "name or service not known",
                "connection refused",
                "connection timed out",
                "network connection closed",
                "no route to host",
            ),
        )

    @property
    def is_timeout_error(self) -> bool:
        return "svn command timed out after" in self.output_text.lower()

    @property
    def is_already_exists_error(self) -> bool:
        return _contains_any(
            self.output_text,
            (
                "e160020",
                "already exists",
                "already exist",
                "file already exists",
                "path already exists",
                "is already under version control",
            ),
        )

    @property
    def is_out_of_date_error(self) -> bool:
        return _contains_any(
            self.output_text,
            (
                "e155011",
                "e160028",
                "out of date",
                "out-of-date",
                "working copy is out of date",
                "base checksum mismatch",
            ),
        )

    @property
    def is_property_not_found(self) -> bool:
        lowered = self.output_text.lower()
        return "w200017" in lowered or (
            "property" in lowered and "not found" in lowered
        )

    @property
    def category(self) -> str:
        if self.is_timeout_error:
            return "timeout"
        if self.is_authentication_error:
            return "authentication"
        if self.is_authorization_error:
            return "authorization"
        if self.is_local_repository_not_found:
            return "not_found"
        if self.is_network_error:
            return "network"
        if self.is_property_not_found:
            return "property_not_found"
        if self.is_path_not_found:
            return "not_found"
        return "unknown"

    def __str__(self) -> str:
        return redact_url_credentials(
            f"svn command failed (code {self.returncode}): {self.cmd}\n"
            f"STDERR:\n{self.stderr}\n"
            f"STDOUT:\n{self.stdout}"
        )


class SVNOutputLimitError(SVNCommandError):
    """Raised when a bounded SVN stdout stream exceeds its configured limit."""

    @property
    def category(self) -> str:
        return "output_limit"
