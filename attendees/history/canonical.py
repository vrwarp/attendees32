"""The form a record takes in the history, and the seal over it.

A snapshot is the record as plain JSON: one key per tracked field, named
by the column (``division_id``, not ``division``), holding the JSON types
only. Dates, decimals, UUIDs, files and anything else JSON has no form for
become strings, so a snapshot written on one database backend reads the
same on another and hydrates back through each field's ``to_python``.

The ledger seals each event with an HMAC over the previous event's seal
and the event's own content; ``mac_for`` is the one definition of what is
sealed, used by the writer, the verifier and the copy from pghistory.
"""
import base64
import datetime
import decimal
import hashlib
import hmac
import json
import math
import uuid

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models.fields.files import FieldFile
from django.utils.functional import Promise

GENESIS = "0" * 64  # the ``prev_mac`` of the first event, and the head's mac before any event


def plain(value):
    """``value`` as the JSON types the snapshot column stores."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [plain(item) for item in value]
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, (decimal.Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, FieldFile):
        return value.name or ""
    if isinstance(value, Promise):
        return str(value)
    return str(value)  # a PartialDate, a ZoneInfo, whatever else a field holds


def snapshot_of(instance, fields):
    """The record as the history stores it, read from the instance in memory."""
    return {field.attname: plain(getattr(instance, field.attname)) for field in fields}


def snapshot_of_row(row, fields):
    """The same, read from a ``values()`` row."""
    return {field.attname: plain(row.get(field.attname)) for field in fields}


def canonical(snapshot):
    """The one byte-for-byte form of a snapshot: sorted keys, no spaces."""
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def chain_key():
    key = getattr(settings, "HISTORY_CHAIN_KEY", "")
    if not key:
        raise ImproperlyConfigured("HISTORY_CHAIN_KEY is not set; the history ledger needs its key")
    return key.encode("utf-8")


def mac_for(prev_mac, model, object_id, label, created_at, snapshot, key=None):
    """The seal of an event: HMAC-SHA256 over the previous seal and the event."""
    message = "\n".join([prev_mac, model, object_id, label, created_at.isoformat(), canonical(snapshot)])
    return hmac.new(key or chain_key(), message.encode("utf-8"), hashlib.sha256).hexdigest()


def diff(before, after):
    """``{field: (old, new)}`` for every key whose value differs between two snapshots."""
    changes = {}
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key) or (key in before) != (key in after):
            changes[key] = (before.get(key), after.get(key))
    return changes
