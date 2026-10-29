"""One history context per request, resolving the user when the first event is written."""
from .context import begin, end


class HistoryContextMiddleware:
    """Must follow the authentication middleware; the user is read lazily, so a REST
    Framework token authenticated inside the view is seen too."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = begin(f"{request.method} {request.path}", user_getter=lambda: getattr(request, "user", None))
        try:
            return self.get_response(request)
        finally:
            end(token)
