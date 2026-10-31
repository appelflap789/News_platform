"""Plain HTTP fetcher: polite, robots-aware, and unwilling to wander into the local network.

Downloads go through `requests`. That is a deliberate choice: sites behind Cloudflare (Clingendael, for one)
answer `httpx` with a bot challenge whatever it says it is, and serve `requests` normally.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
import time
from collections.abc import Mapping
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

from .. import config
from .base import FetchError, Fetcher, FetchResult, fetchers

REDIRECTS = {301, 302, 303, 307, 308}
RETRY_STATUS = {429, 502, 503, 504}
REFUSALS = {401, 403, 429, 451, 503}
# Imperva's bot check (Incapsula) answers with a "200 OK" page of a few hundred bytes that only loads a script;
# a browser runs it and is let through, anything else stays on that page. Real pages of such sites can carry
# the same script, so only a page this small counts as the check itself.
INCAPSULA_MARK = b"_Incapsula_Resource"
INCAPSULA_MAX_BYTES = 5000
MAX_HOPS = 8
ATTEMPTS = 3
TIMEOUT = (15.0, 30.0)  # connect, read
CHUNK = 65536


@fetchers.register
class HttpFetcher(Fetcher):
    name = "http"
    label = "HTTP"
    description = "Direct HTTP requests. Fast; does not run JavaScript."

    def __init__(self) -> None:
        self._session = requests.Session()
        self._lock = threading.Lock()
        self._next_slot: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    # -- public ---------------------------------------------------------------

    def fetch(self, url: str, *, max_bytes: int | None = None, robots: bool = True) -> FetchResult:
        limit = max_bytes or int(float(config.get("max_download_mb")) * 1024 * 1024)
        current = url
        for _ in range(MAX_HOPS):
            self._guard(current, robots)
            status, headers, body = self._get(current, limit)
            if status in REDIRECTS and headers.get("location"):
                current = urljoin(current, headers["location"])
                continue
            if status == 403 and headers.get("cf-mitigated") == "challenge":
                raise FetchError(f"{urlsplit(current).hostname} answered with a Cloudflare bot challenge, which "
                                 f"only a real browser can pass (HTTP 403 for {current})", refused=True, status=403)
            if status >= 400:
                raise FetchError(f"HTTP {status} for {current}", refused=status in REFUSALS, status=status)
            if len(body) < INCAPSULA_MAX_BYTES and INCAPSULA_MARK in body:
                raise FetchError(f"{urlsplit(current).hostname} answered with an Imperva (Incapsula) bot check "
                                 f"instead of the page ({current}). The platform does not try to get past it; such "
                                 f"a site lets it through at some times and not at others, so try again later",
                                 refused=True, status=status)
            content_type = headers.get("content-type", "").lower()
            return FetchResult(
                url=current,
                status=status,
                content_type=content_type.split(";")[0].strip(),
                content=body,
                encoding=_charset(content_type),
            )
        raise FetchError(f"Too many redirects for {url}")

    # -- checks ---------------------------------------------------------------

    def _guard(self, url: str, robots: bool) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise FetchError(f"Not a web address: {url}")
        if config.get("block_private_hosts") and _is_private(parts.hostname):
            raise FetchError(f"Refusing to fetch a local network address: {parts.hostname}")
        if robots and config.get("respect_robots") and not self._allowed_by_robots(url):
            raise FetchError(f"robots.txt disallows {url}", refused=True)

    def _allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(origin)
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self._agent_token(), url)

    def _load_robots(self, origin: str) -> RobotFileParser | None:
        try:
            response = self._session.get(f"{origin}/robots.txt", headers=self._headers(), timeout=10.0)
        except requests.RequestException:
            return None
        if response.status_code >= 400:
            return None
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser

    def sitemaps_from_robots(self, url: str) -> list[str]:
        """Sitemap URLs a site advertises in robots.txt (used by the analyzers)."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(origin)
        parser = self._robots[origin]
        return list(parser.site_maps() or []) if parser else []

    # -- transport --------------------------------------------------------------

    def _get(self, url: str, limit: int) -> tuple[int, Mapping[str, str], bytes]:
        host = urlsplit(url).netloc
        last_error = "no response"
        for attempt in range(ATTEMPTS):
            self._wait_for_slot(host)
            try:
                with self._session.get(url, headers=self._headers(), stream=True, allow_redirects=False,
                                       timeout=TIMEOUT) as response:
                    self._note_rate_limit(host, response.headers)
                    if response.status_code in RETRY_STATUS and attempt < ATTEMPTS - 1:
                        last_error = f"HTTP {response.status_code}"
                        time.sleep(_retry_delay(response, attempt))
                        continue
                    body = bytearray()
                    for chunk in response.iter_content(CHUNK):
                        body.extend(chunk)
                        if len(body) > limit:
                            raise FetchError(f"{url} is larger than {limit // (1024 * 1024)} MB")
                    return response.status_code, response.headers, bytes(body)
            except requests.RequestException as error:
                last_error = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
                if attempt < ATTEMPTS - 1:
                    time.sleep(2**attempt)
        raise FetchError(f"Could not fetch {url} ({last_error})")

    def _wait_for_slot(self, host: str) -> None:
        """Space out requests to the same host."""
        delay = float(config.get("request_delay_seconds"))
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = slot + delay
        if slot > now:
            time.sleep(slot - now)

    def _note_rate_limit(self, host: str, headers: Mapping[str, str]) -> None:
        """When a site says its quota is used up, hold the next request to it until the quota resets."""
        try:
            remaining = float(headers["x-ratelimit-remaining"])
            reset = float(headers["x-ratelimit-reset"])
        except (KeyError, ValueError):
            return
        if remaining < 1:
            with self._lock:
                self._next_slot[host] = max(self._next_slot.get(host, 0.0), time.monotonic() + min(reset, 60.0) + 0.5)

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": str(config.get("user_agent")),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
            "Accept-Language": "en,nl;q=0.8",
        }

    def _agent_token(self) -> str:
        return str(config.get("user_agent")).split("/")[0].split(" ")[0] or "*"


def _charset(content_type: str) -> str:
    if "charset=" in content_type:
        return content_type.split("charset=")[-1].split(";")[0].strip().strip("\"'")
    return ""


def _retry_delay(response: requests.Response, attempt: int) -> float:
    for header in ("retry-after", "x-ratelimit-reset"):
        try:
            return min(float(response.headers[header]), 30.0) + 0.5
        except (KeyError, ValueError):
            continue
    return float(2 ** (attempt + 1))


def _is_private(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as error:
        raise FetchError(f"Cannot find the server {host}") from error
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if (
            address.is_private or address.is_loopback or address.is_link_local
            or address.is_reserved or address.is_multicast or address.is_unspecified
        ):
            return True
    return False
