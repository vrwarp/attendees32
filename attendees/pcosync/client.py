"""A Planning Center People JSON:API client, pointed at pcomirror.

There is no "pcomirror protocol". pcomirror serves Planning Center's own API --
same paths, same query grammar, same envelope -- so this client speaks plain PCO
and simply has its base URL aimed at the mirror. Tally reached the same
conclusion and it is why its client needed no mirror-specific code either.

Reading through the mirror does buy three things the real API cannot give, and
each shows up below as a deliberate behaviour rather than an accident:

* ``410 Gone`` carrying ``meta.merged_into``, so a merged person forwards to the
  survivor instead of simply vanishing into a 404;
* ``504`` carrying ``meta.write_indeterminate``, an honest "this may or may not
  have been applied";
* ``meta.mirror.oldest_last_synced_at``, the mirror's own statement of how stale
  it is, which is what lets a caller refuse to push from a stale read.

Most of the rest is ported from ``tally/functions/src/pco/client.ts``. Every
behaviour marked below was paid for in production; none of them are theoretical.
"""

import json
import logging
import time
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterator, Optional
from urllib.parse import urlencode, urljoin, urlsplit

import requests

logger = logging.getLogger(__name__)

REDACTED = "[redacted]"
MAX_TRACE_BODY_CHARS = 4000
BASE_BACKOFF_MS = 500
MAX_BACKOFF_MS = 20_000
DEFAULT_MAX_RETRIES = 4
DEFAULT_MAX_PAGES = 500
MIRROR_MAX_PER_PAGE = 100
MAX_MERGE_HOPS = 5

#: POST is absent on purpose. There is no idempotency key to send, so a create
#: whose response was lost is indistinguishable from one that never left. Tally's
#: log has a single "add a parent" retried five times, creating five real people.
REPLAYABLE_METHODS = frozenset({"GET", "PATCH", "DELETE"})

_SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "set-cookie"})


def build_query_string(query: Optional[dict]) -> str:
    """Encode PCO's nested filter grammar.

    ``{"where": {"updated_at": {"gte": iso}}, "include": ["emails"]}`` becomes
    ``where[updated_at][gte]=<iso>&include=emails``. Brackets are left literal
    rather than percent-encoded: the server accepts both and a log line you can
    read is worth more than strict conformance here.
    """
    if not query:
        return ""

    pairs: list[tuple[str, str]] = []

    def walk(prefix: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                walk(f"{prefix}[{sub_key}]" if prefix else str(sub_key), sub_value)
        elif isinstance(value, (list, tuple, set)):
            items = [str(item) for item in value if item is not None]
            if items:
                pairs.append((prefix, ",".join(items)))
        elif isinstance(value, bool):
            pairs.append((prefix, "true" if value else "false"))
        else:
            pairs.append((prefix, str(value)))

    walk("", query)
    return urlencode(pairs, safe="[]")


def redact_headers(headers: Optional[dict]) -> dict:
    """Strip credentials before a trace can escape this module.

    Done at trace construction rather than at logging time, so there is never an
    unredacted copy lying around for a later code path to leak.
    """
    if not headers:
        return {}
    return {
        key: (REDACTED if key.lower() in _SENSITIVE_HEADERS else value)
        for key, value in headers.items()
    }


@dataclass(frozen=True)
class PcoRequestTrace:
    method: str
    url: str
    headers: dict = dataclass_field(default_factory=dict)
    attempts: int = 1


@dataclass(frozen=True)
class PcoResponseTrace:
    status: int
    headers: dict = dataclass_field(default_factory=dict)
    body: str = ""
    body_truncated: bool = False
    duration_ms: int = 0


class PcoError(Exception):
    """Base for everything this module raises."""


class PcoNetworkError(PcoError):
    """The request never became a response: DNS, TLS, reset, timeout.

    Kept distinct from an API error because "Planning Center said no" and "we
    could not get there" need different words in front of a volunteer, and the
    second has no status line to quote.
    """

    def __init__(self, message, *, request=None, cause=None):
        super().__init__(message)
        self.request = request
        self.cause = cause


class PcoApiError(PcoError):
    def __init__(self, message, *, status, path, errors=None,
                 request=None, response=None, retry_after_ms=None):
        super().__init__(message)
        self.status = status
        self.path = path
        self.errors = errors or []
        self.request = request
        self.response = response
        self.retry_after_ms = retry_after_ms

    @property
    def first_meta(self) -> dict:
        if self.errors and isinstance(self.errors[0], dict):
            meta = self.errors[0].get("meta")
            if isinstance(meta, dict):
                return meta
        return {}


class PcoGoneError(PcoApiError):
    """410: the record is a tombstone. It may still name its survivor."""

    @property
    def merged_into(self) -> Optional[str]:
        value = self.first_meta.get("merged_into")
        return str(value) if value not in (None, "") else None

    @property
    def deleted_at(self) -> Optional[str]:
        return self.first_meta.get("deleted_at")

    @property
    def tombstone_reason(self) -> Optional[str]:
        return self.first_meta.get("tombstone_reason")


class PcoWriteIndeterminate(PcoApiError):
    """504 + ``meta.write_indeterminate``: it may or may not have been applied.

    pcomirror emits this specifically to stop a client retrying, and it sets
    ``safe_to_retry: false`` to say so in as many words. Treating it as an
    ordinary gateway error -- and retrying -- would throw away the one guarantee
    the mirror offers that raw Planning Center cannot.
    """

    @property
    def safe_to_retry(self) -> bool:
        return bool(self.first_meta.get("safe_to_retry", False))


@dataclass(frozen=True)
class Page:
    data: list
    included: list
    meta: dict
    links: dict
    url: str
    index: int

    @property
    def mirror_oldest_synced_at(self) -> Optional[str]:
        mirror = self.meta.get("mirror")
        return mirror.get("oldest_last_synced_at") if isinstance(mirror, dict) else None


class PcoMirrorClient:
    """Talks to one pcomirror (or to Planning Center itself).

    ``sleep`` and ``now`` are injected so tests exercise the retry curve without
    waiting for it.
    """

    def __init__(self, base_url, api_key, *, session=None, sleep=time.sleep,
                 now=None, max_retries=DEFAULT_MAX_RETRIES,
                 max_pages=DEFAULT_MAX_PAGES, timeout=(10, 60),
                 user_agent="attendees32-pcosync/1.0"):
        if not base_url:
            raise ValueError("pcomirror base_url is required")
        if not api_key:
            raise ValueError("pcomirror api_key is required")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.session = session or requests.Session()
        self.sleep = sleep
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.max_retries = max_retries
        self.max_pages = max_pages
        self.timeout = timeout
        self.user_agent = user_agent
        #: Set from the freshest response seen, for the staleness guard.
        self.last_mirror_oldest_synced_at: Optional[str] = None

    # -- plumbing ---------------------------------------------------------

    def _headers(self, has_body: bool) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def url_for(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _backoff_ms(self, attempt: int, retry_after_ms: Optional[int]) -> int:
        if retry_after_ms is not None:
            return retry_after_ms
        return min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * (2 ** attempt))

    def _parse_retry_after(self, headers) -> Optional[int]:
        raw = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
        if not raw:
            return None
        raw = str(raw).strip()
        if raw.isdigit():
            return int(raw) * 1000
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        delta_ms = int((when - self.now()).total_seconds() * 1000)
        return max(0, delta_ms)

    @staticmethod
    def _read_failure_body(response) -> tuple[str, bool]:
        """Read an error body as text, never as JSON.

        The bodies that most need explaining are exactly the ones that are not
        JSON: gateway timeouts, WAF blocks, proxy error pages. Calling
        ``.json()`` on those trades a readable message for a decode traceback.
        """
        try:
            text = response.text or ""
        except Exception:  # pragma: no cover - a body that will not even decode
            return "<unreadable response body>", False
        if len(text) > MAX_TRACE_BODY_CHARS:
            return text[:MAX_TRACE_BODY_CHARS], True
        return text, False

    @staticmethod
    def _errors_from(text: str) -> list:
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return []
        errors = parsed.get("errors") if isinstance(parsed, dict) else None
        return errors if isinstance(errors, list) else []

    def _raise_for(self, method, url, path, response, request_trace, attempts):
        text, truncated = self._read_failure_body(response)
        response_trace = PcoResponseTrace(
            status=response.status_code,
            headers=redact_headers(dict(response.headers or {})),
            body=text,
            body_truncated=truncated,
        )
        errors = self._errors_from(text)
        request_trace = PcoRequestTrace(
            method=request_trace.method, url=request_trace.url,
            headers=request_trace.headers, attempts=attempts,
        )
        detail = ""
        if errors and isinstance(errors[0], dict):
            detail = errors[0].get("detail") or errors[0].get("title") or ""
        message = f"{method} {path} failed with {response.status_code}"
        if detail:
            message = f"{message}: {detail}"

        common = dict(status=response.status_code, path=path, errors=errors,
                      request=request_trace, response=response_trace)

        if response.status_code == 410:
            raise PcoGoneError(message, **common)
        if response.status_code == 504:
            meta = {}
            if errors and isinstance(errors[0], dict):
                meta = errors[0].get("meta") or {}
            if isinstance(meta, dict) and meta.get("write_indeterminate"):
                raise PcoWriteIndeterminate(
                    f"{method} {path} reached Planning Center but its response "
                    f"was lost, so it may or may not have been applied",
                    **common,
                )
        raise PcoApiError(
            message,
            retry_after_ms=self._parse_retry_after(response.headers),
            **common,
        )

    def request(self, method: str, path: str, *, query=None, body=None) -> dict:
        method = method.upper()
        replayable = method in REPLAYABLE_METHODS
        url = self.url_for(path)
        qs = build_query_string(query)
        if qs:
            url = f"{url}?{qs}"
        headers = self._headers(body is not None)
        trace = PcoRequestTrace(method=method, url=url,
                                headers=redact_headers(headers))

        attempt = 0
        while True:
            attempts = attempt + 1
            started = time.monotonic()
            try:
                response = self.session.request(
                    method, url, headers=headers,
                    json=body if body is not None else None,
                    timeout=self.timeout,
                )
            except Exception as exc:  # transport-level: no status line exists
                if replayable and attempt < self.max_retries:
                    self.sleep(self._backoff_ms(attempt, None) / 1000.0)
                    attempt += 1
                    continue
                raise PcoNetworkError(
                    f"could not reach Planning Center for {method} {path}: {exc}",
                    request=PcoRequestTrace(method=method, url=url,
                                            headers=trace.headers, attempts=attempts),
                    cause=exc,
                ) from exc

            duration_ms = int((time.monotonic() - started) * 1000)

            if 200 <= response.status_code < 300:
                return self._decode_success(response, method, path, trace,
                                            attempts, duration_ms)

            if self._should_retry(response.status_code, replayable, response) \
                    and attempt < self.max_retries:
                retry_after = self._parse_retry_after(response.headers)
                self.sleep(self._backoff_ms(attempt, retry_after) / 1000.0)
                attempt += 1
                continue

            self._raise_for(method, url, path, response, trace, attempts)

    def _should_retry(self, status, replayable, response) -> bool:
        # 429 is retried for every verb, POST included: a rate-limit refusal
        # happens before anything could have been written, so replaying it
        # cannot duplicate a record.
        if status == 429:
            return True
        if status == 504:
            text, _ = self._read_failure_body(response)
            errors = self._errors_from(text)
            meta = errors[0].get("meta") if errors and isinstance(errors[0], dict) else None
            if isinstance(meta, dict) and meta.get("write_indeterminate"):
                return False
        return replayable and status >= 500

    def _decode_success(self, response, method, path, trace, attempts, duration_ms):
        if response.status_code == 204 or not (response.content or b""):
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            text, truncated = self._read_failure_body(response)
            raise PcoApiError(
                f"{method} {path} returned {response.status_code} with a body "
                f"that is not JSON",
                status=response.status_code, path=path,
                request=PcoRequestTrace(method=trace.method, url=trace.url,
                                        headers=trace.headers, attempts=attempts),
                response=PcoResponseTrace(
                    status=response.status_code,
                    headers=redact_headers(dict(response.headers or {})),
                    body=text, body_truncated=truncated, duration_ms=duration_ms,
                ),
            ) from exc
        self._note_mirror_freshness(payload)
        return payload

    def _note_mirror_freshness(self, payload):
        meta = payload.get("meta") if isinstance(payload, dict) else None
        mirror = meta.get("mirror") if isinstance(meta, dict) else None
        if isinstance(mirror, dict):
            oldest = mirror.get("oldest_last_synced_at")
            if oldest:
                self.last_mirror_oldest_synced_at = oldest

    # -- verbs ------------------------------------------------------------

    def get(self, path, query=None) -> dict:
        return self.request("GET", path, query=query)

    def post(self, path, body) -> dict:
        return self.request("POST", path, body=body)

    def patch(self, path, body) -> dict:
        return self.request("PATCH", path, body=body)

    def delete(self, path) -> dict:
        return self.request("DELETE", path)

    # -- pagination -------------------------------------------------------

    def paginate(self, path, query=None, per_page=MIRROR_MAX_PER_PAGE,
                 max_pages=None) -> Iterator[Page]:
        """Walk a collection, handling all four cursor shapes.

        pcomirror paginates by offset only. Three of the four cases below are
        obvious; the third is the one that matters. A page that comes back full
        with no cursor at all is ambiguous, and the two readings cost very
        differently: assuming the walk is over silently truncates an entire
        organization, while assuming there is more costs one empty request. So
        we step the offset ourselves.
        """
        limit = max_pages or self.max_pages
        query = dict(query or {})
        query["per_page"] = per_page
        query.setdefault("offset", 0)

        url = self.url_for(path)
        qs = build_query_string(query)
        current = f"{url}?{qs}" if qs else url
        seen: set[str] = set()
        offset = int(query["offset"])
        index = 0

        while True:
            if index >= limit:
                raise PcoApiError(
                    f"pagination of {path} exceeded {limit} pages; refusing to "
                    f"continue in case this is a cursor loop",
                    status=0, path=path,
                )
            if current in seen:
                # A cursor that repeats itself is a loop, not a long collection.
                return
            seen.add(current)

            payload = self.request("GET", current)
            data = payload.get("data") or []
            if not isinstance(data, list):
                data = [data]
            page = Page(
                data=data,
                included=payload.get("included") or [],
                meta=payload.get("meta") or {},
                links=payload.get("links") or {},
                url=current,
                index=index,
            )
            yield page
            index += 1

            if not data:
                return

            next_url = self._next_url(page, current, offset, per_page, len(data))
            if not next_url:
                return
            offset += per_page
            current = next_url

    def _next_url(self, page, current, offset, per_page, row_count):
        # 1. links.next, resolved against the URL that served this page. PCO
        #    sends it as a path; resolving it against base_url instead loses any
        #    query string and breaks on page two.
        link = page.links.get("next")
        if link:
            try:
                return urljoin(current, link)
            except ValueError:
                pass

        # 2. meta.next.offset, if it actually advances.
        meta_next = page.meta.get("next")
        if isinstance(meta_next, dict) and meta_next.get("offset") is not None:
            try:
                next_offset = int(meta_next["offset"])
            except (TypeError, ValueError):
                next_offset = None
            if next_offset is not None and next_offset > offset:
                return _with_offset(current, next_offset)

        # 3. A full page with no cursor: step the offset ourselves.
        if row_count >= per_page:
            return _with_offset(current, offset + per_page)

        # 4. A short page is the end of the walk.
        return None

    def paginate_records(self, path, query=None, per_page=MIRROR_MAX_PER_PAGE,
                         max_pages=None) -> Iterator[dict]:
        for page in self.paginate(path, query, per_page, max_pages):
            for record in page.data:
                yield record

    # -- merges -----------------------------------------------------------

    def follow_person_link(self, person_id, from_error=None, query=None):
        """Walk a merge chain to the surviving person.

        Returns ``(surviving_id, resource_or_None)``, or ``(None, None)`` when
        the chain ends in a record that is simply gone. ``from_error`` lets a
        caller hand back the 410 it already holds, so the common case costs no
        extra request.

        Hop-capped and cycle-guarded: an organization where somebody merged in a
        circle should not become an infinite loop here.
        """
        seen = {str(person_id)}
        current = str(person_id)
        error = from_error

        for _ in range(MAX_MERGE_HOPS):
            if error is None:
                try:
                    payload = self.get(f"/people/{current}", query)
                    return current, payload.get("data")
                except PcoGoneError as exc:
                    error = exc
                except PcoApiError as exc:
                    if exc.status == 404:
                        return None, None
                    raise

            survivor = error.merged_into if isinstance(error, PcoGoneError) else None
            if not survivor or survivor in seen:
                return None, None
            seen.add(survivor)
            current = survivor
            error = None

        logger.warning("merge chain from person %s exceeded %s hops",
                       person_id, MAX_MERGE_HOPS)
        return None, None


def _with_offset(url: str, offset: int) -> str:
    """Replace ``offset`` in a URL's query string, leaving everything else."""
    parts = urlsplit(url)
    pairs = []
    replaced = False
    if parts.query:
        for chunk in parts.query.split("&"):
            if not chunk:
                continue
            key, _, value = chunk.partition("=")
            if key == "offset":
                pairs.append(f"offset={offset}")
                replaced = True
            else:
                pairs.append(f"{key}={value}" if value or "=" in chunk else key)
    if not replaced:
        pairs.append(f"offset={offset}")
    query = "&".join(pairs)
    base = f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.scheme else parts.path
    return f"{base}?{query}" if query else base
