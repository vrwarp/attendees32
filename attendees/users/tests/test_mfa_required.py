"""Staff and superusers must have a second factor; members may."""
import pytest
from allauth.mfa.models import Authenticator
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from attendees.middleware import MFARequiredMiddleware
from attendees.users.adapters import mfa_missing, mfa_required

pytestmark = pytest.mark.django_db


def through(request):
    return MFARequiredMiddleware(lambda request: HttpResponse("page"))(request)


def test_staff_and_superusers_must_have_a_second_factor_and_members_need_not(django_user_model):
    member = django_user_model.objects.create_user(username="member", email="m@example.com", password="pw")
    staff = django_user_model.objects.create_user(username="staff", email="s@example.com", password="pw", is_staff=True)
    boss = django_user_model.objects.create_superuser(username="boss", email="b@example.com", password="pw")
    assert not mfa_required(member) and mfa_required(staff) and mfa_required(boss)
    assert not mfa_required(AnonymousUser())
    assert mfa_missing(staff)
    Authenticator.objects.create(user=staff, type=Authenticator.Type.TOTP, data={"secret": "x"})
    assert not mfa_missing(staff)


def test_the_setting_extends_the_requirement_to_everyone(django_user_model, settings):
    member = django_user_model.objects.create_user(username="member", email="m@example.com", password="pw")
    settings.MFA_ENFORCED = True
    assert mfa_required(member)


def test_a_staff_member_without_a_second_factor_is_sent_to_enrol(django_user_model):
    staff = django_user_model.objects.create_user(username="staff", email="s@example.com", password="pw", is_staff=True)
    request = RequestFactory().get("/persons/attendee/")
    request.user = staff
    response = through(request)
    assert response.status_code == 302 and response["Location"].startswith(reverse("mfa_index"))


def test_the_enrolment_pages_logout_and_static_files_stay_open(django_user_model):
    staff = django_user_model.objects.create_user(username="staff", email="s@example.com", password="pw", is_staff=True)
    for path in (reverse("mfa_index"), "/accounts/2fa/totp/activate/", "/accounts/logout/", "/static/css/project.css"):
        request = RequestFactory().get(path)
        request.user = staff
        assert through(request).status_code == 200, path


def test_an_api_call_is_refused_rather_than_redirected(django_user_model):
    staff = django_user_model.objects.create_user(username="staff", email="s@example.com", password="pw", is_staff=True)
    request = RequestFactory().get("/persons/api/datagrid_data_attendees/")
    request.user = staff
    response = through(request)
    assert response.status_code == 403
    assert b"second factor" in response.content


def test_members_and_enrolled_staff_pass(django_user_model):
    member = django_user_model.objects.create_user(username="member", email="m@example.com", password="pw")
    staff = django_user_model.objects.create_user(username="staff", email="s@example.com", password="pw", is_staff=True)
    Authenticator.objects.create(user=staff, type=Authenticator.Type.TOTP, data={"secret": "x"})
    for user in (member, staff, AnonymousUser()):
        request = RequestFactory().get("/persons/attendee/")
        request.user = user
        assert through(request).status_code == 200
