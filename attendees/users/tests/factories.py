from typing import Any, Sequence

from django.contrib.auth import get_user_model
from factory import Faker, post_generation
from factory.django import DjangoModelFactory


class UserFactory(DjangoModelFactory):

    username = Faker("user_name")
    email = Faker("email")
    name = Faker("name")

    @post_generation
    def password(self, create: bool, extracted: Sequence[Any], **kwargs):
        password = (
            extracted
            if extracted
            else Faker(
                "password",
                length=42,
                special_chars=True,
                digits=True,
                upper_case=True,
                lower_case=True,
            ).evaluate(None, None, extra={"locale": None})
        )
        self.set_password(password)

    class Meta:
        model = get_user_model()
        django_get_or_create = ["username"]


#: A base32 secret for the authenticator app a test superuser is enrolled with.
TEST_TOTP_SECRET = "TESTSUPERUSERSECONDFACTOR2345677"


def enrol_second_factor(user, secret=TEST_TOTP_SECRET):
    """Give ``user`` an authenticator app: staff and superusers cannot open a page without one."""
    from allauth.mfa.totp.internal.auth import TOTP

    TOTP.activate(user, secret)
    return user
