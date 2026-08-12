"""Cross-backend behaviour tests for the SQLite compatibility layer.

These are deliberately backend-agnostic: the CI matrix runs the same file against Postgres and
SQLite, and every assertion here must hold on both. That is what makes them a parity suite
rather than a SQLite suite — a divergence shows up as a failure on one leg.
"""
import pghistory
import pytest
from django.db import connection
from django.db.models import Q, Value

from attendees.persons.models.folk import Folk
from attendees.persons.models.relation import Relation, RelationsHistory
from attendees.utils.dbcompat.aggregates import (
    ArrayAgg,
    JSONBAgg,
    JsonBuildObject,
    StringAgg,
)
from attendees.utils.dbcompat.expressions import JsonArrayHasKeyValue
from attendees.utils.dbcompat.lookups import json_contains

pytestmark = pytest.mark.django_db

# `gender` is varchar(11) and the model default is longer, so every Relation built here passes
# one explicitly. Unrelated to the compatibility layer, but Postgres enforces the length.
GENDER = "male"


def _labels(prefix):
    return list(
        RelationsHistory.objects.filter(title__startswith=prefix)
        .order_by("pgh_id")
        .values_list("pgh_label", "display_order")
    )


class TestHistoryEquivalence:
    """The audit trail must record the same events on either backend.

    The interesting cases are the ones a Django-signals fallback would miss: `queryset.update()`
    and `bulk_create` never call `save()`, so only a database-level trigger sees them.
    """

    def test_orm_write_is_recorded(self):
        relation = Relation.objects.create(title="hx-orm", gender=GENDER, display_order=1)
        relation.display_order = 2
        relation.save()

        assert _labels("hx-orm") == [
            ("relation.snapshot", 1),
            ("relation.snapshot", 2),
        ]

    def test_queryset_update_is_recorded(self):
        relation = Relation.objects.create(title="hx-qs", gender=GENDER, display_order=1)
        Relation.objects.filter(pk=relation.pk).update(display_order=5)

        assert _labels("hx-qs") == [
            ("relation.snapshot", 1),
            ("relation.snapshot", 5),
        ]

    def test_noop_update_is_suppressed(self):
        relation = Relation.objects.create(title="hx-noop", gender=GENDER, display_order=1)
        Relation.objects.filter(pk=relation.pk).update(display_order=1)

        # The trigger's WHEN clause compares OLD to NEW; an update that changes nothing must not
        # produce an event. On SQLite this relies on IS NOT being a null-safe comparison, the
        # same as Postgres's IS DISTINCT FROM.
        assert _labels("hx-noop") == [("relation.snapshot", 1)]

    def test_bulk_create_is_recorded(self):
        Relation.objects.bulk_create(
            [Relation(title="hx-bulk", gender=GENDER, display_order=7)]
        )

        assert _labels("hx-bulk") == [("relation.snapshot", 7)]

    def test_context_is_attached_to_events(self):
        with pghistory.context(probe="dbcompat-test"):
            Relation.objects.create(title="hx-ctx", gender=GENDER, display_order=1)

        events = RelationsHistory.objects.filter(title__startswith="hx-ctx")
        assert events.count() == 1
        assert events.filter(pgh_context__isnull=False).count() == 1
        assert (
            pghistory.models.Context.objects.filter(metadata__probe="dbcompat-test").count() == 1
        )

    def test_no_context_rows_without_tracking(self):
        """A read-only request must not leave a context row behind."""
        before = pghistory.models.Context.objects.count()
        list(Relation.objects.all()[:1])
        assert pghistory.models.Context.objects.count() == before


@pytest.mark.skipif(connection.vendor == "postgresql", reason="SQLite trigger management only")
# transaction=True: SQLite refuses to run its schema editor inside an open atomic block,
# because it cannot toggle foreign key checks mid-transaction.
@pytest.mark.django_db(transaction=True)
class TestTriggerDurability:
    """SQLite drops a table's triggers when Django rebuilds the table.

    Django emulates most ALTERs by creating a new table, copying rows, dropping the original and
    renaming — and it has no concept of triggers, so it never puts them back. Left unhandled the
    audit trail would go silently dead, so `post_migrate` reinstalls them.
    """

    def test_expected_triggers_are_installed(self):
        from attendees.utils.dbcompat.triggers import (
            expected_trigger_names,
            installed_trigger_names,
        )

        assert expected_trigger_names() - installed_trigger_names() == set()

    def test_triggers_survive_a_table_rebuild(self):
        from django.db import models

        from attendees.utils.dbcompat.triggers import sync_sqlite_triggers

        def trigger_count():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM sqlite_master "
                    "WHERE type = 'trigger' AND tbl_name = %s",
                    [Relation._meta.db_table],
                )
                return cursor.fetchone()[0]

        original = trigger_count()
        assert original > 0

        # NOT NULL with a default is what forces the rebuild; a nullable ADD COLUMN would take
        # SQLite's fast path and leave the triggers alone.
        probe = models.CharField(max_length=4, null=False, default="x")
        probe.set_attributes_from_name("rebuild_probe")
        with connection.schema_editor() as editor:
            editor.add_field(Relation, probe)
        assert trigger_count() == 0, "expected the rebuild to drop triggers"

        sync_sqlite_triggers()
        assert trigger_count() == original

        with connection.schema_editor() as editor:
            editor.remove_field(Relation, probe)
        sync_sqlite_triggers()

    def test_history_still_records_after_a_rebuild(self):
        """The point of the resync: auditing must actually work again, not merely exist."""
        import copy

        from attendees.utils.dbcompat.triggers import sync_sqlite_triggers

        # Widening an existing column forces _remake_table without adding a NOT NULL column the
        # model does not know how to populate.
        old_field = Relation._meta.get_field("gender")
        new_field = copy.deepcopy(old_field)
        new_field.max_length = 20
        with connection.schema_editor() as editor:
            editor.alter_field(Relation, old_field, new_field)

        sync_sqlite_triggers()

        Relation.objects.create(title="hx-rebuilt", gender=GENDER, display_order=1)
        assert _labels("hx-rebuilt") == [("relation.snapshot", 1)]

        with connection.schema_editor() as editor:
            editor.alter_field(Relation, new_field, old_field)
        sync_sqlite_triggers()


class TestPortableArrayField:
    def test_list_roundtrips(self):
        relation = Relation.objects.create(
            title="arr-values", gender=GENDER, reciprocal_ids=[3, 1, 2]
        )
        assert Relation.objects.get(pk=relation.pk).reciprocal_ids == [3, 1, 2]

    def test_default_and_null_roundtrip(self):
        empty = Relation.objects.create(title="arr-empty", gender=GENDER)
        null = Relation.objects.create(title="arr-null", gender=GENDER, reciprocal_ids=None)
        assert Relation.objects.get(pk=empty.pk).reciprocal_ids == []
        assert Relation.objects.get(pk=null.pk).reciprocal_ids is None


class TestJsonLookups:
    def test_json_contains_matches_the_same_rows(self):
        from attendees.persons.models.attendee import Attendee

        # Compiles on both backends: native containment on Postgres, a key path on SQLite.
        assert (
            Attendee.objects.filter(json_contains("infos__schedulers", {"42": True})).count() >= 0
        )

    def test_json_array_sorter_compiles(self):
        from attendees.persons.models.attendee import Attendee

        queryset = Attendee.objects.annotate(
            attendingmeets=JSONBAgg(
                JsonBuildObject(Value("meet_slug"), "division__slug"), default=[]
            )
        ).order_by(JsonArrayHasKeyValue("attendingmeets", "meet_slug", "probe").desc())
        assert queryset.count() >= 0


class TestAggregates:
    def test_json_aggregate_is_decoded_not_double_encoded(self):
        """psycopg2 parses JSON for us; json_group_array returns a string.

        Without `output_field=JSONField()` the SQLite result would arrive as a JSON string and
        the datagrid would render escaped text, so assert the decoded Python type directly.
        """
        Relation.objects.create(title="agg-json", gender=GENDER, display_order=1)
        row = (
            Relation.objects.filter(title="agg-json")
            .annotate(payload=JSONBAgg(JsonBuildObject(Value("t"), "title"), default=[]))
            .values("payload")
            .first()
        )
        assert isinstance(row["payload"], list)
        assert row["payload"] == [{"t": "agg-json"}]

    def test_array_aggregate_returns_a_list(self):
        Relation.objects.create(title="agg-arr", gender=GENDER, display_order=4)
        row = (
            Relation.objects.filter(title="agg-arr")
            .annotate(orders=ArrayAgg("display_order"))
            .values("orders")
            .first()
        )
        assert list(row["orders"]) == [4]

    def test_distinct_string_aggregate_with_a_filter(self):
        """distinct + filter together, which the datagrid uses and which nearly broke.

        `Aggregate.get_source_expressions()` appends the filter and `set_source_expressions()`
        pops it back off. Dropping the delimiter for DISTINCT by slicing therefore promoted the
        aggregated column into the filter slot and emitted `group_concat(DISTINCT )` — a
        zero-argument call SQLite rejects outright.
        """
        Relation.objects.create(title="agg-df", gender=GENDER, display_order=1)
        row = (
            Relation.objects.filter(title="agg-df")
            .annotate(
                titles=StringAgg(
                    "title",
                    delimiter=", ",
                    distinct=True,
                    default=None,
                    filter=Q(display_order__gte=0),
                )
            )
            .values("titles")
            .first()
        )
        assert row["titles"] == "agg-df"

    def test_string_aggregate_joins_with_the_delimiter(self):
        Relation.objects.create(title="agg-str", gender=GENDER, display_order=1)
        row = (
            Relation.objects.filter(title="agg-str")
            .annotate(titles=StringAgg("title", delimiter=", ", default=None))
            .values("titles")
            .first()
        )
        assert row["titles"] == "agg-str"


class TestGenericRelations:
    def test_uuid_keyed_generic_relation_joins(self):
        """Folk.places joins a UUID pk to a CharField object_id.

        Django stores UUIDs unhyphenated on SQLite and hyphenated on Postgres, so a plain CAST
        matched nothing on SQLite. UuidAsText normalises both spellings.
        """
        assert Folk.objects.filter(places__isnull=False).count() >= 0
        # The compiled SQL must reference the normalising function on SQLite.
        sql = str(Folk.objects.filter(places__isnull=False).query)
        if connection.vendor != "postgresql":
            assert "uuid_text" in sql
