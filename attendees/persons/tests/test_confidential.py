"""Who may see a confidential record: its viewers, or anyone when it has none."""
import pytest
from django.apps import apps
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType

from attendees.persons.models import Attendee, Category, FolkAttendee, Note, Past, Relation, Utility
from attendees.persons.models.enum import GenderEnum
from attendees.whereabouts.models import Division, Organization


@pytest.mark.django_db
class TestConfidential:
    def setup_method(self):
        self.organization = Organization.objects.create(display_name="Test Organization", slug="test-org")
        group = Group.objects.create(name="Test Group")
        self.division = Division.objects.create(
            organization=self.organization, display_name="Test Division", slug="test-division", audience_auth_group=group
        )
        Relation.objects.create(id=0, title="self", gender=GenderEnum.UNSPECIFIED.value)
        Category.objects.create(id=0, display_name="Family")
        Category.objects.create(id=25, display_name="Non-family")
        self.note_category = Category.objects.create(type="note", display_name="counseling")
        self.subject = self.person("Grace")
        self.counselor, self.coworker = self.person("Jian"), self.person("Jon")

    def person(self, first):
        return Attendee.objects.create(first_name=first, last_name="Chen", division=self.division, gender="unspecified")

    def past(self, name, viewers=(), **fields):
        past = Past.objects.create(
            content_type=ContentType.objects.get_for_model(Attendee),
            object_id=str(self.subject.id),
            category=self.note_category,
            organization=self.organization,
            display_name=name,
            infos=Utility.relationship_infos(),
            **fields,
        )
        past.viewers.set(viewers)
        return past

    def test_a_record_with_no_viewers_is_for_everyone_and_one_with_viewers_for_them_only(self):
        public = self.past("public")
        kept = self.past("kept", viewers=[self.counselor, self.coworker])

        for reader, expected in ((self.counselor, {public, kept}), (self.coworker, {public, kept}), (self.subject, {public})):
            visible = Past.objects.filter(Past.visible_to(reader.id), organization=self.organization)
            assert set(visible) == expected, reader
            assert visible.count() == len(expected), "no row is counted once per viewer"
        assert kept.is_visible_to(self.counselor.id) and not kept.is_visible_to(self.subject.id)
        assert set(Past.objects.filter(Past.visible_to(None))) == {public}, "a reader with no attendee sees the open ones"

    def test_every_confidential_model_answers_the_same_way(self):
        note = Note.objects.create(
            content_type=ContentType.objects.get_for_model(Attendee),
            object_id=str(self.subject.id),
            category=self.note_category,
            organization=self.organization,
            body="between us",
        )
        note.viewers.add(self.counselor)
        membership = FolkAttendee.objects.get(attendee=self.subject)
        membership.viewers.add(self.coworker)
        assert list(Note.objects.filter(Note.visible_to(self.counselor.id))) == [note]
        assert list(Note.objects.filter(Note.visible_to(self.coworker.id))) == []
        assert list(FolkAttendee.objects.filter(FolkAttendee.visible_to(self.coworker.id), attendee=self.subject)) == [membership]
        assert list(FolkAttendee.objects.filter(FolkAttendee.visible_to(self.counselor.id), attendee=self.subject)) == []

    def test_the_backfill_turns_show_secret_into_viewers_and_the_counselors_flag(self):
        import importlib

        secret = self.past("secret")
        for_counselors = self.past("counselors")
        Past.objects.filter(pk=secret.pk).update(
            infos={**secret.infos, "show_secret": {str(self.counselor.id): True, str(self.coworker.id): False}}
        )
        Past.objects.filter(pk=for_counselors.pk).update(infos={**for_counselors.infos, "show_secret": {"all_counselors_": True}})

        importlib.import_module("attendees.persons.migrations.0020_links_and_viewers_backfill").copy_viewers(apps, None)

        secret.refresh_from_db()
        for_counselors.refresh_from_db()
        assert list(secret.viewers.all()) == [self.counselor] and not secret.counselors_may_view
        assert list(for_counselors.viewers.all()) == [] and for_counselors.counselors_may_view
        assert "show_secret" not in secret.infos and "show_secret" not in for_counselors.infos
