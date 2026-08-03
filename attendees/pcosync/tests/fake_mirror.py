"""An in-process stand-in for pcomirror, for tests that must not touch a socket.

Two ways to feed it, and they answer different questions:

``load_golden()`` replays the sanitized recordings in ``golden/``. Those are real
responses from a real organization, so they answer "does the client understand
what the server actually sends" -- including the parts nobody would think to
invent, like a ``sequence`` gap in the custom-field tab.

``add_collection()`` synthesizes a paginated collection with a chosen cursor
shape. Recordings cannot answer "what happens on page two when the server omits
``links.next``", because a recording is one page from one server. Tally's
simulator learned this the expensive way: its default cursor shape was the one
production did not use, so every test passed while every multi-page roster
failed. Hence ``shape``.

``strict=True`` (the default) raises on any request that was not set up, so a
test cannot pass because the client quietly asked for something else.
``write_log`` records every mutation, which is usually the assertion that
actually matters: not what the client returned, but what it *did*.
"""

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

#: Cursor shapes a collection response can use. The client must survive all four.
SHAPE_RELATIVE_LINKS = "links"          # what pcomirror sends
SHAPE_ABSOLUTE_LINKS = "absolute-links"  # what Planning Center sends
SHAPE_META_ONLY = "meta"                # meta.next.offset and nothing else
SHAPE_NO_CURSOR = "no-cursor"           # a full page with no cursor at all


class FakeResponse:
    """Just enough of ``requests.Response`` for the client to work with."""

    def __init__(self, status_code, body=None, headers=None, text=None):
        self.status_code = status_code
        self.headers = headers or {}
        if text is not None:
            self._text = text
        elif body is None:
            self._text = ""
        else:
            self._text = json.dumps(body)
        self._body = body

    @property
    def content(self):
        return self._text.encode("utf-8")

    @property
    def text(self):
        return self._text

    def json(self):
        return json.loads(self._text)


class UnrecordedRequest(AssertionError):
    pass


def normalise_query(query_string):
    """Order-insensitive, so a test is not hostage to dict iteration order."""
    if not query_string:
        return ()
    return tuple(sorted(parse_qsl(query_string, keep_blank_values=True)))


class FakeMirror:
    """A ``requests.Session`` look-alike backed by canned answers."""

    def __init__(self, strict=True):
        self.strict = strict
        self._routes = {}          # (method, path, normalised_query) -> response
        self._path_routes = {}     # (method, path) -> response, any query
        self.calls = []            # every request, in order
        self.write_log = []        # POST/PATCH/DELETE only
        self._failures = {}        # (method, path) -> [pending failures]

    # -- setup ------------------------------------------------------------

    def add(self, method, path, response, query=None):
        key = (method.upper(), path, normalise_query(query))
        self._routes[key] = response
        return self

    def add_any_query(self, method, path, response):
        self._path_routes[(method.upper(), path)] = response
        return self

    def load_golden(self, *names):
        """Replay recorded pairs by file stem."""
        for name in names:
            payload = json.loads((GOLDEN_DIR / f"{name}.json").read_text())
            request, response = payload["request"], payload["response"]
            self.add(
                request.get("method", "GET"),
                request["path"],
                FakeResponse(response.get("status", 200), response.get("body")),
                query=request.get("query"),
            )
        return self

    def golden_body(self, name):
        return json.loads((GOLDEN_DIR / f"{name}.json").read_text())["response"]["body"]

    def add_collection(self, path, records, per_page=100,
                       shape=SHAPE_RELATIVE_LINKS, base="/people/v2"):
        """Serve ``records`` as pages of ``per_page``, using ``shape`` for cursors."""
        total = len(records)
        # range() with an empty list still needs one (empty) page to exist.
        starts = list(range(0, total, per_page)) or [0]
        for offset in starts:
            chunk = records[offset:offset + per_page]
            has_more = offset + per_page < total
            body = {
                "data": chunk,
                "meta": {"total_count": total, "count": len(chunk)},
                "links": {},
            }
            if has_more:
                nxt = offset + per_page
                if shape == SHAPE_RELATIVE_LINKS:
                    body["links"]["next"] = (
                        f"{base}{path}?per_page={per_page}&offset={nxt}"
                    )
                elif shape == SHAPE_ABSOLUTE_LINKS:
                    body["links"]["next"] = (
                        f"https://api.planningcenteronline.com{base}{path}"
                        f"?per_page={per_page}&offset={nxt}"
                    )
                elif shape == SHAPE_META_ONLY:
                    body["meta"]["next"] = {"offset": nxt}
                elif shape == SHAPE_NO_CURSOR:
                    pass  # deliberately no cursor; the client must step offset
                else:  # pragma: no cover - programming error in a test
                    raise ValueError(f"unknown pagination shape {shape!r}")
            self.add("GET", path, FakeResponse(200, body),
                     query=f"per_page={per_page}&offset={offset}")

        # One empty page past the end, which is what a real server answers for
        # an out-of-range offset. It is reached whenever the collection is an
        # exact multiple of per_page: the last page comes back full, so the
        # client cannot yet tell the walk is over and probes once more.
        self.add(
            "GET", path,
            FakeResponse(200, {"data": [], "meta": {"total_count": total, "count": 0},
                               "links": {}}),
            query=f"per_page={per_page}&offset={starts[-1] + per_page}",
        )
        return self

    def fail_once(self, method, path, *, status=None, exception=None,
                  body=None, headers=None, times=1):
        """Queue transient failures ahead of the recorded answer."""
        key = (method.upper(), path)
        pending = self._failures.setdefault(key, [])
        for _ in range(times):
            pending.append({"status": status, "exception": exception,
                            "body": body, "headers": headers})
        return self

    # -- the session interface -------------------------------------------

    def request(self, method, url, headers=None, json=None, timeout=None):
        method = method.upper()
        parts = urlsplit(url)
        path = parts.path
        for prefix in ("/people/v2", "/check-ins/v2"):
            if path.startswith(prefix):
                path = path[len(prefix):] or "/"
        query = normalise_query(parts.query)

        self.calls.append({"method": method, "path": path, "query": query,
                           "url": url, "body": json,
                           "headers": dict(headers or {})})
        if method != "GET":
            self.write_log.append({"method": method, "path": path, "body": json})

        pending = self._failures.get((method, path))
        if pending:
            failure = pending.pop(0)
            if failure["exception"] is not None:
                raise failure["exception"]
            return FakeResponse(failure["status"], failure["body"],
                                headers=failure["headers"])

        route = self._routes.get((method, path, query))
        if route is None:
            route = self._path_routes.get((method, path))
        if route is None:
            if self.strict:
                raise UnrecordedRequest(
                    f"no canned answer for {method} {path} {dict(query)}"
                )
            return FakeResponse(404, {"errors": [{"code": "404",
                                                  "detail": "not found"}]})
        return route

    # -- assertions -------------------------------------------------------

    def paths_called(self, method=None):
        return [c["path"] for c in self.calls
                if method is None or c["method"] == method.upper()]

    def count(self, method, path):
        return sum(1 for c in self.calls
                   if c["method"] == method.upper() and c["path"] == path)


def error_body(code, detail, meta=None):
    error = {"code": str(code), "detail": detail}
    if meta is not None:
        error["meta"] = meta
    return {"errors": [error]}
