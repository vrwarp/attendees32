from django.contrib.contenttypes.models import ContentType
from django.db import connection, migrations


FORWARD = f"""
                ALTER TABLE {ContentType._meta.db_table}
                  ADD COLUMN IF NOT EXISTS display_order SMALLINT DEFAULT 0 NOT NULL,
                  ADD COLUMN IF NOT EXISTS genres VARCHAR(100) DEFAULT NULL,
                  ADD COLUMN IF NOT EXISTS endpoint VARCHAR(100) DEFAULT NULL,
                  ADD COLUMN IF NOT EXISTS hint VARCHAR(100) DEFAULT NULL;

                CREATE INDEX IF NOT EXISTS django_content_genres
                   ON {ContentType._meta.db_table} (genres);
                """

BACKWARD = f"""
                DROP INDEX IF EXISTS django_content_genres;

                ALTER TABLE {ContentType._meta.db_table}
                    DROP COLUMN IF EXISTS hint,
                    DROP COLUMN IF EXISTS endpoint,
                    DROP COLUMN IF EXISTS genres,
                    DROP COLUMN IF EXISTS display_order;
                 """


class Migration(migrations.Migration):
    """
    Raw SQL since there is no control over Django's ContentType model
    """

    dependencies = [
        ('whereabouts', '0000_initial'),
        ('contenttypes', '0002_remove_content_type_name'),

    ]

    operations = [
        # The columns were PostgreSQL's (ADD COLUMN IF NOT EXISTS); Phase 4 moved their data into
        # ContentTypeExtra and dropped them, so another database never gets them at all.
        migrations.RunSQL(sql=FORWARD if connection.vendor == "postgresql" else migrations.RunSQL.noop,
                          reverse_sql=BACKWARD if connection.vendor == "postgresql" else migrations.RunSQL.noop),
    ]
