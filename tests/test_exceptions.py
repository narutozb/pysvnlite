from __future__ import annotations

from pysvnlite.exceptions import SVNCommandError, redact_url_credentials


def test_svn_error_classifies_path_not_found() -> None:
    error = SVNCommandError(["svn", "list"], 1, "", "E160013: path not found")

    assert error.is_path_not_found
    assert error.category == "not_found"


def test_svn_error_classifies_authentication() -> None:
    error = SVNCommandError(["svn", "list"], 1, "", "E215004: authentication failed")

    assert error.is_authentication_error
    assert error.category == "authentication"


def test_svn_error_classifies_authorization() -> None:
    error = SVNCommandError(["svn", "list"], 1, "", "E170001: Authorization failed")

    assert error.is_authorization_error
    assert error.category == "authorization"


def test_svn_error_classifies_network() -> None:
    error = SVNCommandError(["svn", "list"], 1, "", "E000110: connection timed out")

    assert error.is_network_error
    assert error.category == "network"


def test_svn_error_classifies_missing_file_repository_before_network() -> None:
    url = "file:///tmp/definitely-missing-repository"
    error = SVNCommandError(
        ["svn", "--non-interactive", "info", "--xml", url],
        1,
        "",
        (
            f"E170013: Unable to connect to a repository at URL '{url}'\n"
            f"E180001: Unable to open repository '{url}'"
        ),
    )

    assert error.is_local_repository_not_found
    assert error.is_path_not_found
    assert error.is_network_error
    assert error.category == "not_found"


def test_svn_error_keeps_remote_unable_to_connect_as_network() -> None:
    url = "https://svn.example.invalid/repository"
    error = SVNCommandError(
        ["svn", "--non-interactive", "info", "--xml", url],
        1,
        "",
        f"E170013: Unable to connect to a repository at URL '{url}'",
    )

    assert not error.is_local_repository_not_found
    assert error.category == "network"


def test_svn_error_prioritizes_auth_over_missing_path_text() -> None:
    error = SVNCommandError(
        ["svn", "list"],
        1,
        "",
        "E170001: Authorization failed\nURL does not exist",
    )

    assert error.is_path_not_found
    assert error.category == "authorization"


def test_svn_error_detects_already_exists() -> None:
    error = SVNCommandError(["svn", "mkdir"], 1, "", "E160020: File already exists")

    assert error.is_already_exists_error


def test_svn_error_detects_out_of_date() -> None:
    error = SVNCommandError(["svn", "commit"], 1, "", "E155011: Directory is out of date")

    assert error.is_out_of_date_error


def test_svn_error_classifies_missing_property() -> None:
    error = SVNCommandError(
        ["svn", "propget"],
        1,
        "",
        "W200017: Property 'demo:missing' not found on 'svn://repo'",
    )

    assert error.is_property_not_found
    assert error.category == "property_not_found"


def test_svn_error_redacts_url_credentials_from_display_text() -> None:
    url = "https://build-user:top-secret@svn.example.com/packages"
    error = SVNCommandError(
        ["svn", "list", url],
        1,
        "",
        f"Unable to connect to {url}",
    )

    displayed = str(error)
    assert "build-user" not in displayed
    assert "top-secret" not in displayed
    assert "https://***@svn.example.com/packages" in displayed
    assert redact_url_credentials(url) == "https://***@svn.example.com/packages"
