"""URL rules for settings and outbound calls (ANALYSIS.md Section 3.7).

Only `http` and `https`, no user name or password, and `localhost` or
`127.0.0.1` mapped to `host.docker.internal` so a container can reach a
service on the Mac. Errors are `UrlError` with a message a person can act on.
"""

from __future__ import annotations

from urllib.parse import SplitResult, urlsplit, urlunsplit

MAX_URL_LENGTH = 2048
DOCKER_HOST = "host.docker.internal"

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})
_ALLOWED_SCHEMES = frozenset({"http", "https"})


class UrlError(ValueError):
    """A URL that breaks the rules. The message is meant to be shown to the user."""


def _parse(url: str) -> SplitResult:
    """Splits a URL and checks what every address needs, whatever it is used for."""
    if len(url) > MAX_URL_LENGTH:
        raise UrlError(f"The address is too long (the limit is {MAX_URL_LENGTH} characters).")
    if any(char.isspace() or not char.isprintable() for char in url):
        raise UrlError("The address must not contain spaces or control characters.")

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UrlError("This is not a valid address.") from exc

    if parts.scheme not in _ALLOWED_SCHEMES:
        raise UrlError("Use an http:// or https:// address.")
    if not parts.hostname:
        raise UrlError("The address needs a host name, for example http://localhost:8012.")
    if "@" in parts.netloc:
        raise UrlError("Remove the user name and password from the address.")
    if port == 0:
        raise UrlError("The port must be a number from 1 to 65535.")
    return parts


def validate_base_url(raw: str) -> str:
    """Checks a URL typed into Settings and returns it as it will be stored.

    Stored as typed, only trimmed and without trailing slashes. A query string
    or fragment is refused because the app appends its own paths.
    """
    url = raw.strip()
    parts = _parse(url)
    if "?" in url or "#" in url:
        raise UrlError("Remove everything after the address path: no ? and no #.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def check_request_url(url: str) -> None:
    """Checks a URL about to be called. Unlike a base URL, it may carry a query string."""
    _parse(url)


def docker_mapped(url: str) -> str:
    """Replaces a `localhost` or `127.0.0.1` host with `host.docker.internal`.

    Any other URL is returned unchanged, and so is one that cannot be parsed
    (`check_request_url` rejects that later).
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return url

    if parts.hostname not in _LOCAL_HOSTS:
        return url
    netloc = DOCKER_HOST if port is None else f"{DOCKER_HOST}:{port}"
    return urlunsplit(parts._replace(netloc=netloc))


def join_url(base: str, path: str) -> str:
    """Joins a base URL and a path with exactly one slash between them."""
    return f"{base.rstrip('/')}/{path.lstrip('/')}"
