from rest_framework.permissions import BasePermission

from attendees.users.models import Menu


class DrfSpyGuard(BasePermission):
    """
    DRF-native port of SpyGuard, for API viewsets that token-authenticated
    server-to-server clients (e.g. the Tally integration) must be able to call.

    Django-level guards (UserPassesTestMixin / login_required) run in dispatch()
    *before* DRF performs authentication, so a request carrying a valid
    ``Authorization: Token …`` header is still anonymous when they check it and
    gets redirected to the login page. A DRF permission runs after
    authentication, which makes session and token requests equal citizens.

    The rules are SpyGuard.test_func verbatim, with two deliberate differences:
    no ``time.sleep(2)`` tarpit (an API client just retries, so it only slows
    legitimate callers), and denial is DRF's standard 403 JSON rather than a
    hand-written HttpResponse.
    """

    message = "Do you have attendee associated with your user? You do not have permissions to visit this!"

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        targeting_attendee_id = request.META.get(
            "HTTP_X_TARGET_ATTENDEE_ID", view.kwargs.get("attendee_id")
        )
        current_attendee = user.attendee if hasattr(user, "attendee") else None

        if targeting_attendee_id == "new":
            return Menu.user_can_create_attendee(user)
        if targeting_attendee_id:
            if current_attendee:
                if str(current_attendee.id) == targeting_attendee_id:
                    return True
                if current_attendee.under_same_org_with(targeting_attendee_id):
                    return (
                        user.can_see_all_organizational_meets_attendees()
                        or current_attendee.can_schedule_attendee(targeting_attendee_id)
                    )
            return False
        return request.resolver_match.url_name == Menu.ATTENDEE_UPDATE_SELF
