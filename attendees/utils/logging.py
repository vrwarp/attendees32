"""Logging filters that keep personal data out of the logs."""
import logging
import re

#: A path followed by a query string; the path is kept, the query string goes.
QUERY_STRING = re.compile(r"(/[^\s\"'?]*)\?[^\s\"']*")


class StripQueryString(logging.Filter):
    """Drop the query string from any URL in a log record.

    The roster and directory pages carry the search term and the person's
    key in the query string, so an access line that kept it would record who
    looked for whom. The path alone is kept, in the message and in its
    arguments (the request line is an argument for ``django.server`` and
    ``uvicorn.access``).
    """

    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = self._strip(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: self._strip(value) for key, value in record.args.items()}
            else:
                record.args = tuple(self._strip(value) for value in record.args)
        return True

    @staticmethod
    def _strip(value):
        return QUERY_STRING.sub(r"\1", value) if isinstance(value, str) else value
