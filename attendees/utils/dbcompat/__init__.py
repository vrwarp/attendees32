"""Vendor compatibility layer allowing the project to run on SQLite as well as Postgres.

The single rule this package exists to enforce: **nothing branches on the vendor at import
time.** Django puts index classes and field classes into migration state, so resolving the
vendor while models are being built would give the two backends genuinely different model
state and permanent ``makemigrations`` drift. Every branch here reads
``schema_editor.connection.vendor`` (DDL) or ``connection.vendor`` (queries) instead, so the
model state stays byte-identical and only the emitted SQL differs.
"""

default_app_config = "attendees.utils.dbcompat.apps.DbCompatConfig"
