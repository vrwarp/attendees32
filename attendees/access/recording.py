"""Collecting access entries during a request."""
DETAIL = "detail"
EXPORT = "export"
PRINT = "print"


def record(request, target=None, *, how=DETAIL, endpoint=None, details=None):
    """Note that this request showed ``target`` (a model instance) or produced an export or print.

    The entry is kept on the request and written by ``AccessLogMiddleware``
    once the response is on its way; without the middleware nothing is
    written. ``details`` holds an export's or print's filters, as given.
    """
    # A REST Framework view hands over its Request wrapper, which reads through to the Django
    # request but keeps new attributes to itself; the middleware looks on the Django request.
    request = getattr(request, "_request", request)
    entries = getattr(request, "_access_entries", None)
    if entries is None:
        entries = request._access_entries = []
    entries.append(
        {
            "model": target._meta.concrete_model._meta.label_lower if target is not None else "",
            "object_id": str(target.pk) if target is not None else "",
            "how": how,
            "endpoint": endpoint or _endpoint(request),
            "details": details,
        }
    )


def _endpoint(request):
    match = getattr(request, "resolver_match", None)
    if match is not None and match.url_name:
        return (f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name)[:200]
    return request.path[:200]
