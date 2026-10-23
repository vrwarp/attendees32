# Vendored from django-pghistory 2.4.2 so the stored procedure can be skipped on SQLite.
#
# Upstream installs `_pgh_attach_context()` as a PL/pgSQL function, unconditionally. On SQLite
# the equivalent is registered per connection as a Python function by our database backend
# (see attendees/db/backends/sqlite3/base.py), so there is nothing to install here.
#
# Registered through MIGRATION_MODULES in config/settings/base.py.

from django.db import migrations

from pghistory.models import Context


def install_pgh_attach_context_func(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    Context.install_pgh_attach_context_func(using=schema_editor.connection.alias)


class Migration(migrations.Migration):

    dependencies = [
        ("pghistory", "0003_auto_20201023_1636"),
    ]

    operations = [
        migrations.RunPython(
            install_pgh_attach_context_func, reverse_code=migrations.RunPython.noop
        )
    ]
