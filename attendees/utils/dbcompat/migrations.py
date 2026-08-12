"""Migration operations that carry a different statement list per backend."""
from django.db import migrations


class VendorSQL:
    """A bundle of SQL statement lists keyed by database vendor.

    Built by the ``Utility`` SQL helpers and consumed by :class:`PortableRunSQL`. A vendor with
    no entry contributes no statements, which is the common case: most of this project's raw
    SQL sets Postgres column defaults or writes table comments, and neither has — or needs — a
    SQLite equivalent.
    """

    def __init__(self, **by_vendor):
        self.by_vendor = {vendor: list(sqls) for vendor, sqls in by_vendor.items()}

    def for_vendor(self, vendor):
        return self.by_vendor.get(vendor, [])

    def __repr__(self):
        vendors = ", ".join(sorted(self.by_vendor))
        return f"<VendorSQL {vendors}>"


class PortableRunSQL(migrations.RunSQL):
    """``RunSQL`` that selects its statements by vendor and runs them one at a time.

    Accepts either a :class:`VendorSQL` or anything plain ``RunSQL`` accepts, so it can be
    dropped in at a call site whose SQL turns out to be portable after all.
    """

    def _resolve(self, schema_editor, sql):
        if isinstance(sql, VendorSQL):
            return sql.for_vendor(schema_editor.connection.vendor)
        return sql

    def _run_sql(self, schema_editor, sqls):
        resolved = self._resolve(schema_editor, sqls)
        if isinstance(resolved, list) and not resolved:
            return
        super()._run_sql(schema_editor, resolved)

    def describe(self):
        return "Raw SQL operation (vendor-aware)"
