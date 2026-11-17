"""Which addresses the tool may open. Only public http and https addresses.

The Mac is on a private network and runs the Visio Studio app on localhost, so an address that
leads there is refused, whether it is written as an address or reached by a name, a redirect or
a DNS answer that changes.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Final
from urllib.parse import urljoin, urlsplit

import httpx

from . import MAX_PDF_BYTES, MAX_REDIRECTS, PAGE_LOAD_TIMEOUT_S
from .rounds import TEXT_LIMITS, Refused

_Address = ipaddress.IPv4Address | ipaddress.IPv6Address

DOWNLOAD_USER_AGENT: Final = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/159.0.0.0 Safari/537.36"
)


def _is_public(address: _Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def check_address_text(text: str) -> None:
    """Refuse an IP address (as the server's address of a response) that is not public."""
    cleaned = text.strip("[]").split("%", 1)[0]
    try:
        address = ipaddress.ip_address(cleaned)
    except ValueError as error:
        raise Refused(f"The server address {text!r} cannot be read.") from error
    if not _is_public(address):
        raise Refused(f"The server answered from a private address ({text}), so it is refused.")


def check_url(url: str) -> None:
    """Refuse a URL that is not a public http or https address. Resolves the host name."""
    if len(url) > TEXT_LIMITS["url"]:
        raise Refused("The address is too long.")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - reading it raises for a bad port
    except ValueError as error:
        raise Refused(f"{url!r} is not a valid address.") from error
    if parts.scheme not in ("http", "https"):
        raise Refused("Only http and https addresses are allowed.")
    if not host:
        raise Refused(f"{url!r} has no host name.")
    if parts.username or parts.password:
        raise Refused("An address with a user name or password is refused (no logins).")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            found = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError as error:
            raise Refused(f"The host name {host!r} cannot be resolved: {error}") from error
        addresses = [ipaddress.ip_address(item[4][0].split("%", 1)[0]) for item in found]
    if not addresses:
        raise Refused(f"The host name {host!r} has no address.")
    for address in addresses:
        if not _is_public(address):
            raise Refused(
                f"{host} leads to a local or private address ({address}). Only public pages "
                "can be captured."
            )


def fetch_pdf(url: str) -> tuple[bytes, str]:
    """Download a PDF. Returns its bytes and the address it finally came from.

    Redirects are followed here, one at a time, so each one is checked. The size is capped while
    streaming, and the file must look like a PDF.
    """
    current = url
    headers = {"User-Agent": DOWNLOAD_USER_AGENT, "Accept": "application/pdf,*/*;q=0.5"}
    timeout = httpx.Timeout(PAGE_LOAD_TIMEOUT_S)
    with httpx.Client(follow_redirects=False, timeout=timeout, headers=headers) as client:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(current)
            try:
                with client.stream("GET", current) as response:
                    stream = response.extensions.get("network_stream")
                    server = stream.get_extra_info("server_addr") if stream else None
                    if server:
                        check_address_text(str(server[0]))
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise Refused("The server redirected without saying where.")
                        current = urljoin(current, location)
                        continue
                    if response.status_code >= 400:
                        raise Refused(f"The server answered {response.status_code} for the PDF.")
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > MAX_PDF_BYTES:
                        raise Refused(
                            f"The PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB."
                        )
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_PDF_BYTES:
                            raise Refused(
                                f"The PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB."
                            )
            except httpx.HTTPError as error:
                raise Refused(f"The PDF could not be downloaded: {error}") from error
            if b"%PDF-" not in bytes(data[:1024]):
                raise Refused(
                    "That address did not give a PDF. For a web page, use the web command."
                )
            return bytes(data), current
    raise Refused(f"The address redirected more than {MAX_REDIRECTS} times.")
