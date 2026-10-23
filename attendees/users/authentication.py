import pghistory
from rest_framework.authentication import TokenAuthentication


class TrackedTokenAuthentication(TokenAuthentication):
    """
    Token authentication that names the caller in the history context.

    pghistory's middleware records the user it finds on the request, and DRF
    authenticates a token inside the view, after the middleware looked. On WSGI
    the middleware patches the request so a later ``request.user`` assignment
    still reaches the context; under ASGI, which is how this server runs, it
    does not, and every change a token client made was recorded as nobody's.
    Naming the user here, in the same thread the writes happen in, closes
    that gap for session and token callers alike.
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            pghistory.context(user=result[0].pk)
        return result
