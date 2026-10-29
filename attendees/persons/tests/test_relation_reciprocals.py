"""Relations name their reciprocals through a table, and the backfill reads the old array."""
import importlib

import pytest

from attendees.persons.models import Relation
from attendees.persons.models.enum import GenderEnum


@pytest.mark.django_db
class TestRelationReciprocals:
    def test_a_relation_names_the_same_tie_from_the_other_side(self):
        father = Relation.objects.create(id=1, title="father", gender=GenderEnum.MALE.value)
        son = Relation.objects.create(id=2, title="son", gender=GenderEnum.MALE.value)
        daughter = Relation.objects.create(id=3, title="daughter", gender=GenderEnum.FEMALE.value)
        father.reciprocals.set([son, daughter])
        assert set(father.reciprocals.all()) == {son, daughter}
        assert list(son.reciprocal_of.all()) == [father]

    def test_the_backfill_copies_the_array_skipping_ids_that_are_not_relations(self):
        migration = importlib.import_module("attendees.persons.migrations.0022_reciprocals_backfill")
        father = Relation.objects.create(id=1, title="father", gender=GenderEnum.MALE.value)
        son = Relation.objects.create(id=2, title="son", gender=GenderEnum.MALE.value)

        class FrozenRelation:
            """What the migration sees: the array still on the row."""
            def __init__(self, relation, ids):
                self.pk = relation.pk
                self.reciprocal_ids = ids

        frozen = [FrozenRelation(father, [2, 99]), FrozenRelation(son, [1])]

        class Manager:
            def all(self):
                return frozen

            def values_list(self, *args, **kwargs):
                return [row.pk for row in frozen]

        class FrozenModel:
            _default_manager = Manager()
            reciprocals = Relation.reciprocals

        class Apps:
            @staticmethod
            def get_model(app, name):
                return FrozenModel

        migration.copy_reciprocals(Apps(), None)
        assert list(father.reciprocals.all()) == [son]
        assert list(son.reciprocals.all()) == [father]
