"""Error reports without personal data: the stack trace goes, the people do not."""


def strip_personal_data(event, hint):
    """A ``before_send`` hook: drop the user, cookies, headers, query string, body and locals from an event.

    Sentry's own ``send_default_pii=False`` already withholds the user and
    cookies; this removes what the Django integration still attaches (the
    request's URL with its query string, headers and data), the breadcrumbs'
    data and any local variables in the stack frames, because the roster's
    and directory's URLs carry names and keys and a frame's locals can hold a
    whole record. What is left is the exception, the stack trace, the
    breadcrumbs' messages and the tags.
    """
    event.pop("user", None)
    request = event.get("request")
    if request:
        url = request.get("url")
        event["request"] = {"method": request.get("method"), "url": url.split("?")[0] if url else None}
    for breadcrumb in (event.get("breadcrumbs") or {}).get("values", []) or []:
        breadcrumb.pop("data", None)
    for exception in (event.get("exception") or {}).get("values", []) or []:
        for frame in (exception.get("stacktrace") or {}).get("frames", []) or []:
            frame.pop("vars", None)
    return event
