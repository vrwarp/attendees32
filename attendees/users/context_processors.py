from django.conf import settings

from attendees.users.adapters import mfa_required


def allauth_settings(request):
    """Expose some settings from django-allauth in templates."""
    return {
        "ACCOUNT_ALLOW_REGISTRATION": settings.ACCOUNT_ALLOW_REGISTRATION,
        "mfa_passkey_login_enabled": getattr(settings, "MFA_PASSKEY_LOGIN_ENABLED", False),
        "mfa_enforced": mfa_required(getattr(request, "user", None)),
    }
