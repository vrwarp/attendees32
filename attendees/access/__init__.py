"""Who saw what: an access row for every detail page, export and print of personal data.

Views call ``record(request, ...)``; the middleware writes the rows after
the response, in a transaction of their own.
"""
from .recording import DETAIL, EXPORT, PRINT, record

__all__ = ["DETAIL", "EXPORT", "PRINT", "record"]
