from django.contrib.contenttypes.models import ContentType
from django.db import migrations

from attendees.utils.dbcompat.migrations import PortableRunSQL, VendorSQL

_TABLE = ContentType._meta.db_table

# SQLite adds one column per ALTER and has no IF NOT EXISTS for columns, so the single
# Postgres statement becomes four. Index DDL is portable as written.
_SQLITE_COLUMNS = [
    "display_order SMALLINT DEFAULT 0 NOT NULL",
    "genres VARCHAR(100) DEFAULT NULL",
    "endpoint VARCHAR(100) DEFAULT NULL",
    "hint VARCHAR(100) DEFAULT NULL",
]


class Migration(migrations.Migration):
    """
    Raw SQL since there is no control over Django's ContentType model
    """

    dependencies = [
        ('whereabouts', '0000_initial'),
        ('contenttypes', '0002_remove_content_type_name'),

    ]

    operations = [
        PortableRunSQL(
            sql=VendorSQL(
                postgresql=[
                    f"""
                ALTER TABLE {_TABLE}
                  ADD COLUMN IF NOT EXISTS display_order SMALLINT DEFAULT 0 NOT NULL,
                  ADD COLUMN IF NOT EXISTS genres VARCHAR(100) DEFAULT NULL,
                  ADD COLUMN IF NOT EXISTS endpoint VARCHAR(100) DEFAULT NULL,
                  ADD COLUMN IF NOT EXISTS hint VARCHAR(100) DEFAULT NULL;
                """,
                    f"CREATE INDEX IF NOT EXISTS django_content_genres ON {_TABLE} (genres);",
                ],
                sqlite=[
                    *[f"ALTER TABLE {_TABLE} ADD COLUMN {column};" for column in _SQLITE_COLUMNS],
                    f"CREATE INDEX IF NOT EXISTS django_content_genres ON {_TABLE} (genres);",
                ],
            ),
            reverse_sql=VendorSQL(
                postgresql=[
                    "DROP INDEX IF EXISTS django_content_genres;",
                    f"""
                ALTER TABLE {_TABLE}
                    DROP COLUMN IF EXISTS hint,
                    DROP COLUMN IF EXISTS endpoint,
                    DROP COLUMN IF EXISTS genres,
                    DROP COLUMN IF EXISTS display_order;
                 """,
                ],
                sqlite=[
                    "DROP INDEX IF EXISTS django_content_genres;",
                    *[
                        f"ALTER TABLE {_TABLE} DROP COLUMN {column.split()[0]};"
                        for column in reversed(_SQLITE_COLUMNS)
                    ],
                ],
            ),
        ),
    ]
