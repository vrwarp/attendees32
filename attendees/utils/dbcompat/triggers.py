"""Compile pgtrigger's history triggers into equivalent SQLite triggers.

Why this is possible at all: SQLite has real row triggers, and they fire on *any* DML — so
``queryset.update()``, ``bulk_create`` and raw SQL are all captured, exactly as on Postgres and
strictly more than a Django-signals fallback would manage.

Everything is compiled from the live ``model._meta.triggers`` objects rather than from the text
baked into migrations, so the two can never drift apart. pgtrigger's compiled representation
already carries the pieces we need — table, when, operation, condition and body — as
``trigger.sql.kwargs``.

The Postgres-to-SQLite mapping is mechanical:

===========================  =========================================================
Postgres                     SQLite
===========================  =========================================================
``NOW()``                    ``_pgh_now()``            (UDF; transaction-start, µs)
``IS DISTINCT FROM``         ``IS NOT``                (identical NULL semantics)
``_pgh_attach_context()``    ``_pgh_attach_context()`` (UDF; name kept identical)
``RETURN NULL;``             dropped                   (no return value in SQLite)
``EXECUTE PROCEDURE fn()``   inline ``BEGIN ... END``  (no stored procedures)
===========================  =========================================================
"""
import re

from django.apps import apps
from django.db import connections

# "RETURN NEW;" / "RETURN OLD;" / "RETURN NULL;" - PL/pgSQL function epilogue with no SQLite
# equivalent; a SQLite trigger body is a bare statement list.
_RETURN_RE = re.compile(r"\bRETURN\s+(?:NEW|OLD|NULL)\s*;", re.IGNORECASE)
_NOW_RE = re.compile(r"\bNOW\(\)", re.IGNORECASE)
_IS_DISTINCT_FROM_RE = re.compile(r"\bIS\s+DISTINCT\s+FROM\b", re.IGNORECASE)
_IS_NOT_DISTINCT_FROM_RE = re.compile(r"\bIS\s+NOT\s+DISTINCT\s+FROM\b", re.IGNORECASE)


def translate_expression(sql):
    """Rewrite a Postgres trigger fragment into its SQLite equivalent."""
    # Order matters: the negated form has to go first or the positive pattern eats its tail.
    sql = _IS_NOT_DISTINCT_FROM_RE.sub("IS", sql)
    sql = _IS_DISTINCT_FROM_RE.sub("IS NOT", sql)
    sql = _NOW_RE.sub("_pgh_now()", sql)
    return sql


def translate_body(func):
    """Rewrite a PL/pgSQL trigger body into a SQLite trigger body."""
    body = _RETURN_RE.sub("", func)
    body = translate_expression(body).strip()
    if not body.endswith(";"):
        body += ";"
    return body


def compile_sqlite_trigger(compiled):
    """Build ``CREATE TRIGGER`` DDL from a ``pgtrigger.compiler.Trigger``.

    Returns ``None`` for triggers we cannot express, rather than emitting SQL that would be
    wrong. Statement-level triggers are the only such case today, and pghistory does not use
    them.
    """
    kwargs = compiled.sql.kwargs
    level = kwargs.get("level", "ROW").upper()
    if level != "ROW":
        return None

    when = kwargs["when"].upper()
    operation = translate_expression(kwargs["operation"])
    table = kwargs["table"]
    name = compiled.sql.pgid

    condition = kwargs.get("condition", "").strip()
    if condition:
        # pgtrigger renders this already prefixed with WHEN (...).
        condition = translate_expression(condition)

    body = translate_body(kwargs["func"])

    return (
        f'CREATE TRIGGER "{name}"\n'
        f'    {when} {operation} ON "{table}"\n'
        f"    FOR EACH ROW {condition}\n"
        f"BEGIN\n"
        f"    {body}\n"
        f"END;"
    )


def iter_triggers():
    """Yield ``(model, compiled_trigger)`` for every registered trigger in the project."""
    for model in apps.get_models():
        for trigger in getattr(model._meta, "triggers", []):
            yield model, trigger.compile(model)


def expected_trigger_names():
    """Names of every trigger that should exist on a SQLite database."""
    names = set()
    for _model, compiled in iter_triggers():
        if compile_sqlite_trigger(compiled) is not None:
            names.add(compiled.sql.pgid)
    return names


def installed_trigger_names(using="default"):
    """Names of the triggers actually present in the SQLite database."""
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        return {row[0] for row in cursor.fetchall()}


def sync_sqlite_triggers(using="default"):
    """Drop and recreate every history trigger. Idempotent, and safe to run often.

    Called from ``post_migrate`` because Django's SQLite ALTER emulation rebuilds tables, and
    a dropped table takes its triggers with it.
    """
    connection = connections[using]
    if connection.vendor == "postgresql":
        return 0

    installed = 0
    with connection.cursor() as cursor:
        for _model, compiled in iter_triggers():
            sql = compile_sqlite_trigger(compiled)
            if sql is None:
                continue
            cursor.execute(f'DROP TRIGGER IF EXISTS "{compiled.sql.pgid}"')
            cursor.execute(sql)
            installed += 1
    return installed
