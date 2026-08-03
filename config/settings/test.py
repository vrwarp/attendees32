"""
With these settings, tests run faster.
"""

from .base import *  # noqa
from .base import env

# GENERAL
ENV_NAME = env('ENV_NAME', default='test.py')  # for mail task
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="cULCU4vlRs3WmS7ivZa8FHOoQl4VgoizOW66QfR1GWHFOKkSLufuuexn8xFNDLKC",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# STATIC FILES
# ------------------------------------------------------------------------------
# django-compressor writes a compiled bundle into STATIC_ROOT on first render,
# which the browser tests neither need nor benefit from: they want the source
# files the finders already serve.
COMPRESS_ENABLED = False

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Your stuff...
# ------------------------------------------------------------------------------
