from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from allauth.mfa.utils import is_mfa_enabled
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse


def mfa_required(user) -> bool:
    """Whether this account must have a second factor.

    Staff and superusers, the roles that see other people's records, always
    must; ``DJANGO_MFA_ENFORCED`` extends that to everyone.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(settings, "MFA_ENFORCED", False) or user.is_staff or user.is_superuser)


def mfa_missing(user) -> bool:
    """Whether ``user`` must have a second factor and has none yet."""
    return mfa_required(user) and not is_mfa_enabled(user)


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request: HttpRequest):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def get_login_redirect_url(self, request):
        if mfa_missing(request.user):
            return reverse("mfa_index")
        return super().get_login_redirect_url(request)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request: HttpRequest, sociallogin: Any):
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

