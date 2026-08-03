"""The whole loop, against a database and a fake mirror.

The behaviours asserted here are the ones a person would notice going wrong:
a dry run that writes something, a second run that undoes the first, a conflict
that quietly disappears, or a status row created twice.
"""

import pytest
from django.contrib.auth.models import Group

from attendees.pcosync.models import PcoDivergence, PcoPersonLink, PcoSyncRun
from attendees.pcosync.services.config import write_config
from attendees.pcosync.services.runner import Runner, run_sync
from attendees.pcosync.services.statuses import attendee_content_type
from attendees.pcosync.tests.fake_mirror import FakeMirror, FakeResponse
from attendees.persons.models import Attendee, Category, GenderEnum, Past, Relation
from attendees.whereabouts.models import Division, Organization

BASE = "https://mirror.test/people/v2"
KEY = "pcm_test_key"

DEFINITION_IDS = {
    "chinese_last_name": "100001",
    "chinese_first_name": "100002",
    "baptized": "100003",
    "believer": "100004",
    "congregation": "100005",
    "attendees_uuid": "100006",
}


def definitions_body():
    return {
        "data": [
            {"type": "FieldDefinition", "id": definition_id,
             "attributes": {"slug": slug, "data_type": "string",
                            "name": slug, "deleted_at": None}}
            for slug, definition_id in DEFINITION_IDS.items()
        ],
        "meta": {"total_count": len(DEFINITION_IDS)}, "links": {},
    }


def person(pco_id, attributes=None, custom=None, emails=(), phones=()):
    """A person plus the side-loads a real include= would bring."""
    included = []
    for slug, value in (custom or {}).items():
        included.append({
            "type": "FieldDatum", "id": f"d{pco_id}{DEFINITION_IDS[slug]}",
            "attributes": {"value": value},
            "relationships": {
                "field_definition": {"data": {"type": "FieldDefinition",
                                              "id": DEFINITION_IDS[slug]}},
                "customizable": {"data": {"type": "Person", "id": str(pco_id)}},
            },
        })
    for index, address in enumerate(emails):
        included.append({
            "type": "Email", "id": f"e{pco_id}{index}",
            "attributes": {"address": address, "primary": index == 0},
            "relationships": {"person": {"data": {"type": "Person",
                                                  "id": str(pco_id)}}},
        })
    for index, number in enumerate(phones):
        included.append({
            "type": "PhoneNumber", "id": f"p{pco_id}{index}",
            "attributes": {"number": number, "primary": index == 0},
            "relationships": {"person": {"data": {"type": "Person",
                                                  "id": str(pco_id)}}},
        })
    return (
        {"type": "Person", "id": str(pco_id), "attributes": attributes or {}},
        included,
    )


def mirror_with(people, uuid_data=None):
    """A mirror answering the three reads a run makes."""
    records, included = [], []
    for record, extra in people:
        records.append(record)
        included.extend(extra)

    mirror = FakeMirror()
    mirror.add_any_query("GET", "/field_definitions",
                         FakeResponse(200, definitions_body()))
    mirror.add_any_query("GET", "/field_data", FakeResponse(200, {
        "data": uuid_data or [], "meta": {"total_count": len(uuid_data or [])},
        "links": {},
    }))
    mirror.add_any_query("GET", "/people", FakeResponse(200, {
        "data": records, "included": included,
        "meta": {"total_count": len(records)}, "links": {},
    }))
    return mirror


@pytest.mark.django_db
class TestRunner:
    def setup_method(self):
        self.organization = Organization.objects.create(
            display_name="Test Organization", slug="testorg",
        )
        self.group = Group.objects.create(name="Test Group")
        self.division = Division.objects.create(
            organization=self.organization, display_name="Chinese Ministry",
            slug="chinese-ministry", audience_auth_group=self.group,
        )
        self.other_division = Division.objects.create(
            organization=self.organization, display_name="Junior Ministry",
            slug="junior-ministry", audience_auth_group=self.group,
        )
        # Mapped to no congregation, so an attendee sitting here reads as
        # "attendees32 holds no congregation" rather than as a rival value.
        self.unmapped_division = Division.objects.create(
            organization=self.organization, display_name="Unassigned",
            slug="unassigned", audience_auth_group=self.group,
        )
        # The status categories the seed data uses: 5 baptized, 4 receive
        # (believer), 22 disbeliever.
        Category.objects.create(id=25, display_name="other", type="generic")
        self.baptized_category = Category.objects.create(
            id=5, display_name="baptized", type="status")
        self.receive_category = Category.objects.create(
            id=4, display_name="receive", type="status")
        self.disbeliever_category = Category.objects.create(
            id=22, display_name="disbeliever", type="status")
        Relation.objects.create(id=0, title="hidden",
                                gender=GenderEnum.UNSPECIFIED.value)

        write_config(self.organization, {
            "enabled": True, "dry_run": True, "push_enabled": False,
            "base_url": BASE, "api_key": KEY,
            "field_definition_tab_id": "183466",
            "congregation_to_division_id": {
                "Chinese": self.division.id,
                "Children": self.other_division.id,
            },
            "status_category_ids": {"baptized": 5, "believer": 4,
                                    "disbeliever": 22},
        })

    # -- helpers ---------------------------------------------------------

    def attendee(self, **kwargs):
        kwargs.setdefault("division", self.division)
        kwargs.setdefault("gender", GenderEnum.UNSPECIFIED.value)
        attendee = Attendee(**kwargs)
        attendee.save()
        return attendee

    def make_run(self, mode=PcoSyncRun.DRY_RUN):
        return PcoSyncRun.objects.create(organization=self.organization,
                                         mode=mode)

    def sync(self, mirror, mode=PcoSyncRun.DRY_RUN, dry_run=None,
             push_enabled=None):
        if dry_run is not None or push_enabled is not None:
            changes = {}
            if dry_run is not None:
                changes["dry_run"] = dry_run
            if push_enabled is not None:
                changes["push_enabled"] = push_enabled
            self.organization.refresh_from_db()
            write_config(self.organization, changes)
        run = self.make_run(mode)
        runner = Runner(run, client=_client(mirror))
        run.state = PcoSyncRun.RUNNING
        run.save()
        runner.resolve_definitions()
        runner.build_uuid_index()
        runner.sync_people()
        run.save()
        return run, runner

    def open_divergences(self, kind=None):
        queryset = PcoDivergence.objects.filter(
            organization=self.organization, resolution=PcoDivergence.OPEN,
            is_removed=False,
        )
        return queryset.filter(kind=kind) if kind else queryset

    # -- identity --------------------------------------------------------

    def test_a_person_carrying_attendees_uuid_links_to_that_attendee(self):
        person_record = self.attendee(first_name="Ann", last_name="Lee")
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(person_record.id)}),
        ])
        _, runner = self.sync(mirror)

        link = PcoPersonLink.objects.get(pco_person_id="900")
        assert link.attendee_id == person_record.id
        assert link.state == PcoPersonLink.LIVE
        assert link.link_source == PcoPersonLink.BY_UUID

    def test_an_unmatched_person_is_reported_and_never_created(self):
        before = Attendee.objects.count()
        mirror = mirror_with([
            person("900", {"first_name": "Stranger", "last_name": "Nobody"}),
        ])
        self.sync(mirror)

        assert Attendee.objects.count() == before, "a sync must not invent people"
        divergence = self.open_divergences(PcoDivergence.UNLINKED_PERSON).get()
        assert divergence.pco_person_id == "900"
        link = PcoPersonLink.objects.get(pco_person_id="900")
        assert link.attendee_id is None
        assert link.state == PcoPersonLink.UNCONFIRMED

    def test_an_unmatched_person_gets_ranked_suggestions(self):
        candidate = self.attendee(first_name="Ann", last_name="Lee")
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"}),
        ])
        self.sync(mirror)

        divergence = self.open_divergences(PcoDivergence.UNLINKED_PERSON).get()
        candidates = divergence.suggestion["candidates"]
        assert candidates, "a same-name attendee should be suggested"
        assert candidates[0]["attendee_id"] == str(candidate.id)
        # ...and suggested only. Nothing was linked.
        assert PcoPersonLink.objects.get(pco_person_id="900").attendee_id is None

    def test_a_soft_deleted_attendee_is_still_found_by_uuid(self):
        """Otherwise the sync creates a second one for a deliberate removal."""
        removed = self.attendee(first_name="Gone", last_name="Away")
        removed.delete()  # SoftDeletableModel: sets is_removed
        mirror = mirror_with([
            person("900", {"first_name": "Gone", "last_name": "Away"},
                   custom={"attendees_uuid": str(removed.id)}),
        ])
        self.sync(mirror)
        assert PcoPersonLink.objects.get(pco_person_id="900").attendee_id \
            == removed.id

    # -- dry run ---------------------------------------------------------

    def test_a_dry_run_writes_nothing_anywhere(self):
        attendee = self.attendee(first_name="Ann", last_name=None)
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id)}),
        ])
        run, _ = self.sync(mirror)

        attendee.refresh_from_db()
        assert attendee.last_name is None, "a dry run must not touch attendees32"
        assert mirror.write_log == [], "a dry run must not touch Planning Center"
        assert run.counts.get("would_write", 0) >= 1

        link = PcoPersonLink.objects.get(pco_person_id="900")
        assert link.baseline.get("last_name") is None, \
            "a dry run must not stamp a baseline either"

    def test_a_dry_run_names_what_it_would_do(self):
        attendee = self.attendee(first_name="Ann", last_name=None)
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id)}),
        ])
        self.sync(mirror)

        would = self.open_divergences(PcoDivergence.WOULD_WRITE)
        pointers = {divergence.pointer for divergence in would}
        assert "$.person.last_name" in pointers

    # -- pulling ---------------------------------------------------------

    def test_a_value_only_planning_center_holds_is_pulled_in(self):
        attendee = self.attendee(first_name="Ann", last_name=None)
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id)}),
        ])
        self.sync(mirror, mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        attendee.refresh_from_db()
        assert attendee.last_name == "Lee"

    def test_pulling_a_name_refreshes_the_derived_search_names(self):
        """Proof the write went through save() rather than around it."""
        attendee = self.attendee(first_name="Ann", last_name=None)
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id)}),
        ])
        self.sync(mirror, mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        attendee.refresh_from_db()
        assert "Lee" in attendee.infos["names"]["original"]
        assert attendee.infos["names"]["romanization"]

    def test_chinese_names_come_across_from_the_custom_fields(self):
        attendee = self.attendee(first_name="Ben", last_name="Tsai")
        mirror = mirror_with([
            person("900", {"first_name": "Ben", "last_name": "Tsai"},
                   custom={"attendees_uuid": str(attendee.id),
                           "chinese_first_name": "秉洲",
                           "chinese_last_name": "蔡"}),
        ])
        self.sync(mirror, mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        attendee.refresh_from_db()
        assert (attendee.first_name2, attendee.last_name2) == ("秉洲", "蔡")

    def test_contacts_land_in_the_infos_slots(self):
        attendee = self.attendee(first_name="Ann", last_name="Lee")
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id)},
                   emails=["ann@example.com"], phones=["(626) 555-0134"]),
        ])
        self.sync(mirror, mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        attendee.refresh_from_db()
        assert attendee.infos["contacts"]["email1"] == "ann@example.com"
        assert attendee.infos["contacts"]["phone1"] == "(626) 555-0134"

    def test_a_congregation_moves_the_attendee_to_its_division(self):
        attendee = self.attendee(first_name="Kid", last_name="Lee",
                                 division=self.unmapped_division)
        mirror = mirror_with([
            person("900", {"first_name": "Kid", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id),
                           "congregation": "Children"}),
        ])
        self.sync(mirror, mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        attendee.refresh_from_db()
        assert attendee.division_id == self.other_division.id

    def test_an_unmapped_congregation_is_reported_rather_than_guessed(self):
        attendee = self.attendee(first_name="Ann", last_name="Lee",
                                 division=self.unmapped_division)
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id),
                           "congregation": "Klingon"}),
        ])
        self.sync(mirror, mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        attendee.refresh_from_db()
        assert attendee.division_id == self.unmapped_division.id, \
            "an unmapped value must not move anybody"
        assert self.open_divergences(PcoDivergence.UNMAPPED_CONGREGATION).exists()

    def test_a_congregation_the_two_sides_disagree_on_is_a_conflict(self):
        """Chinese Ministry locally against Children upstream: nobody wins."""
        attendee = self.attendee(first_name="Ann", last_name="Lee",
                                 division=self.division)
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id),
                           "congregation": "Children"}),
        ])
        self.sync(mirror, mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        attendee.refresh_from_db()
        assert attendee.division_id == self.division.id
        assert self.open_divergences(PcoDivergence.FIELD_CONFLICT).filter(
            pointer="$.person.congregation").exists()

    # -- status rows -----------------------------------------------------

    def test_baptized_true_creates_a_past_row(self):
        attendee = self.attendee(first_name="Ann", last_name="Lee")
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id),
                           "baptized": "true"}),
        ])
        self.sync(mirror, mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        rows = Past.objects.filter(content_type=attendee_content_type(),
                                   object_id=str(attendee.id),
                                   category=self.baptized_category)
        assert rows.count() == 1
        assert rows.first().when is None, \
            "PCO's boolean carries no date; inventing one would be worse"

    def test_a_second_run_does_not_create_a_second_status_row(self):
        attendee = self.attendee(first_name="Ann", last_name="Lee")
        people = [person("900", {"first_name": "Ann", "last_name": "Lee"},
                         custom={"attendees_uuid": str(attendee.id),
                                 "baptized": "true"})]
        self.sync(mirror_with(people), mode=PcoSyncRun.PULL_ONLY, dry_run=False)
        self.sync(mirror_with(people), mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        assert Past.objects.filter(content_type=attendee_content_type(),
                                   object_id=str(attendee.id),
                                   category=self.baptized_category).count() == 1

    def test_a_false_boolean_never_removes_an_existing_status_row(self):
        """A sync does not clear, least of all somebody's baptism record."""
        attendee = self.attendee(first_name="Ann", last_name="Lee")
        Past.objects.create(
            organization=self.organization,
            content_type=attendee_content_type(), object_id=str(attendee.id),
            category=self.baptized_category, display_name="baptized",
        )
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id),
                           "baptized": "false"}),
        ])
        self.sync(mirror, mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        assert Past.objects.filter(content_type=attendee_content_type(),
                                   object_id=str(attendee.id),
                                   category=self.baptized_category,
                                   is_removed=False).exists()

    def test_a_contradictory_believer_record_is_reported(self):
        attendee = self.attendee(first_name="Ann", last_name="Lee")
        for category in (self.receive_category, self.disbeliever_category):
            Past.objects.create(
                organization=self.organization,
                content_type=attendee_content_type(),
                object_id=str(attendee.id), category=category,
                display_name=category.display_name,
            )
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id),
                           "believer": "true"}),
        ])
        self.sync(mirror, mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        conflicts = self.open_divergences(PcoDivergence.FIELD_CONFLICT)
        assert conflicts.filter(pointer="$.person.believer").exists()

    # -- conflicts -------------------------------------------------------

    def test_two_sides_that_both_moved_produce_one_conflict_and_no_write(self):
        attendee = self.attendee(first_name="Ann", last_name="Lee")
        people = [person("900", {"first_name": "Ann", "last_name": "Lee"},
                         custom={"attendees_uuid": str(attendee.id)})]
        # First run: agreement, so a baseline is stamped.
        self.sync(mirror_with(people), mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        # Now both sides move, differently.
        attendee.last_name = "Li"
        attendee.save()
        moved = [person("900", {"first_name": "Ann", "last_name": "Leigh"},
                        custom={"attendees_uuid": str(attendee.id)})]
        self.sync(mirror_with(moved), mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        attendee.refresh_from_db()
        assert attendee.last_name == "Li", "neither side may win a conflict"
        conflicts = self.open_divergences(PcoDivergence.FIELD_CONFLICT).filter(
            pointer="$.person.last_name")
        assert conflicts.count() == 1

    def test_an_unresolved_conflict_stays_one_row_across_runs(self):
        attendee = self.attendee(first_name="Ann", last_name="Lee")
        people = [person("900", {"first_name": "Ann", "last_name": "Lee"},
                         custom={"attendees_uuid": str(attendee.id)})]
        self.sync(mirror_with(people), mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        attendee.last_name = "Li"
        attendee.save()
        moved = [person("900", {"first_name": "Ann", "last_name": "Leigh"},
                        custom={"attendees_uuid": str(attendee.id)})]
        for _ in range(3):
            self.sync(mirror_with(moved), mode=PcoSyncRun.PULL_ONLY,
                      dry_run=False)

        assert self.open_divergences(PcoDivergence.FIELD_CONFLICT).filter(
            pointer="$.person.last_name").count() == 1

    def test_resolving_keep_pco_lets_the_next_run_apply_it(self):
        attendee = self.attendee(first_name="Ann", last_name="Lee")
        people = [person("900", {"first_name": "Ann", "last_name": "Lee"},
                         custom={"attendees_uuid": str(attendee.id)})]
        self.sync(mirror_with(people), mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        attendee.last_name = "Li"
        attendee.save()
        moved = [person("900", {"first_name": "Ann", "last_name": "Leigh"},
                        custom={"attendees_uuid": str(attendee.id)})]
        self.sync(mirror_with(moved), mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        # Resolution is a baseline edit: record the losing side as agreed.
        link = PcoPersonLink.objects.get(pco_person_id="900")
        baseline = dict(link.baseline)
        baseline["last_name"] = "Li"          # what attendees32 held
        link.baseline = baseline
        link.save()
        self.open_divergences(PcoDivergence.FIELD_CONFLICT).update(
            resolution=PcoDivergence.KEEP_PCO)

        self.sync(mirror_with(moved), mode=PcoSyncRun.PULL_ONLY, dry_run=False)
        attendee.refresh_from_db()
        assert attendee.last_name == "Leigh"

    def test_a_field_marked_ignored_stops_being_reported(self):
        attendee = self.attendee(first_name="Ann", last_name="Lee")
        people = [person("900", {"first_name": "Ann", "last_name": "Lee"},
                         custom={"attendees_uuid": str(attendee.id)})]
        self.sync(mirror_with(people), mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        attendee.last_name = "Li"
        attendee.save()
        link = PcoPersonLink.objects.get(pco_person_id="900")
        link.infos = {"ignored_fields": ["last_name"]}
        link.save()

        moved = [person("900", {"first_name": "Ann", "last_name": "Leigh"},
                        custom={"attendees_uuid": str(attendee.id)})]
        self.sync(mirror_with(moved), mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        attendee.refresh_from_db()
        assert attendee.last_name == "Li"
        assert not self.open_divergences(PcoDivergence.FIELD_CONFLICT).filter(
            pointer="$.person.last_name").exists()

    # -- idempotence -----------------------------------------------------

    def test_a_second_identical_run_changes_nothing(self):
        attendee = self.attendee(first_name="Ann", last_name=None)
        people = [person("900", {"first_name": "Ann", "last_name": "Lee"},
                         custom={"attendees_uuid": str(attendee.id)})]
        self.sync(mirror_with(people), mode=PcoSyncRun.PULL_ONLY, dry_run=False)
        attendee.refresh_from_db()
        first_modified = attendee.modified

        run, _ = self.sync(mirror_with(people), mode=PcoSyncRun.PULL_ONLY,
                           dry_run=False)
        attendee.refresh_from_db()
        assert attendee.modified == first_modified, "nothing should be rewritten"
        assert run.counts.get("local_writes", 0) == 0
        assert run.counts.get("conflicts", 0) == 0

    # -- push ------------------------------------------------------------

    def test_push_stays_shut_while_push_enabled_is_off(self):
        attendee = self.attendee(first_name="Ann", last_name="Lee",
                                 first_name2="秉洲")
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id)}),
        ])
        self.sync(mirror, mode=PcoSyncRun.FULL, dry_run=False,
                  push_enabled=False)
        assert mirror.write_log == []

    def test_a_local_only_value_is_pushed_when_push_is_on(self):
        attendee = self.attendee(first_name="Ann", last_name="Lee",
                                 first_name2="秉洲")
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id)}),
        ])
        mirror.add_any_query("POST", "/people/900/field_data",
                             FakeResponse(201, {"data": {"id": "77"}}))
        self.sync(mirror, mode=PcoSyncRun.FULL, dry_run=False,
                  push_enabled=True)

        posted = [w for w in mirror.write_log if w["method"] == "POST"]
        assert any(w["body"]["data"]["attributes"]["value"] == "秉洲"
                   for w in posted)

    def test_the_write_budget_bounds_a_bad_mapping(self):
        for index in range(5):
            self.attendee(first_name=f"P{index}", last_name="Lee",
                          first_name2=f"甲{index}")
        attendees = list(Attendee.objects.order_by("first_name"))
        people = [
            person(f"90{index}", {"first_name": a.first_name,
                                  "last_name": "Lee"},
                   custom={"attendees_uuid": str(a.id)})
            for index, a in enumerate(attendees)
        ]
        mirror = mirror_with(people)
        mirror.add_any_query("POST", "/people/900/field_data",
                             FakeResponse(201, {"data": {"id": "77"}}))
        for index in range(5):
            mirror.add_any_query("POST", f"/people/90{index}/field_data",
                                 FakeResponse(201, {"data": {"id": f"7{index}"}}))

        self.organization.refresh_from_db()
        write_config(self.organization, {"max_writes_per_run": 2})
        self.sync(mirror, mode=PcoSyncRun.FULL, dry_run=False,
                  push_enabled=True)

        assert len([w for w in mirror.write_log if w["method"] == "POST"]) <= 2

    def test_a_refused_write_leaves_the_baseline_alone(self):
        """Otherwise the next run believes the value landed and stops trying."""
        attendee = self.attendee(first_name="Ann", last_name="Lee",
                                 first_name2="秉洲")
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id)}),
        ])
        mirror.add_any_query("POST", "/people/900/field_data",
                             FakeResponse(422, {"errors": [
                                 {"code": "422", "detail": "nope"}]}))
        self.sync(mirror, mode=PcoSyncRun.FULL, dry_run=False,
                  push_enabled=True)

        link = PcoPersonLink.objects.get(pco_person_id="900")
        assert "first_name2" not in link.baseline
        assert self.open_divergences(PcoDivergence.WRITE_REFUSED).exists()

    def test_an_indeterminate_write_is_reported_and_never_repeated(self):
        attendee = self.attendee(first_name="Ann", last_name="Lee",
                                 first_name2="秉洲")
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id)}),
        ])
        mirror.add_any_query("POST", "/people/900/field_data",
                             FakeResponse(504, {"errors": [{
                                 "code": "504", "detail": "response lost",
                                 "meta": {"write_indeterminate": True,
                                          "safe_to_retry": False}}]}))
        self.sync(mirror, mode=PcoSyncRun.FULL, dry_run=False,
                  push_enabled=True)

        assert self.open_divergences(PcoDivergence.WRITE_INDETERMINATE).exists()
        assert len([w for w in mirror.write_log
                    if w["path"] == "/people/900/field_data"]) == 1

    # -- configuration ---------------------------------------------------

    def test_a_missing_custom_field_aborts_before_anything_is_written(self):
        attendee = self.attendee(first_name="Ann", last_name=None)
        mirror = mirror_with([
            person("900", {"first_name": "Ann", "last_name": "Lee"},
                   custom={"attendees_uuid": str(attendee.id)}),
        ])
        thin = {"data": [{"type": "FieldDefinition", "id": "100006",
                          "attributes": {"slug": "attendees_uuid",
                                         "data_type": "string",
                                         "deleted_at": None}}],
                "meta": {}, "links": {}}
        mirror.add_any_query("GET", "/field_definitions",
                             FakeResponse(200, thin))

        run = self.make_run(PcoSyncRun.PULL_ONLY)
        self.organization.refresh_from_db()
        write_config(self.organization, {"dry_run": False})
        run_sync(run, client=_client(mirror))

        run.refresh_from_db()
        assert run.state == PcoSyncRun.FAILED
        attendee.refresh_from_db()
        assert attendee.last_name is None
        assert self.open_divergences(PcoDivergence.CONFIG_MISSING_FIELD).exists()

    def test_a_pilot_list_confines_the_run(self):
        included = self.attendee(first_name="In", last_name=None)
        excluded = self.attendee(first_name="Out", last_name=None)
        mirror = mirror_with([
            person("900", {"first_name": "In", "last_name": "Piloted"},
                   custom={"attendees_uuid": str(included.id)}),
            person("901", {"first_name": "Out", "last_name": "Piloted"},
                   custom={"attendees_uuid": str(excluded.id)}),
        ])
        self.organization.refresh_from_db()
        write_config(self.organization,
                     {"pilot_attendee_ids": [str(included.id)]})
        self.sync(mirror, mode=PcoSyncRun.PULL_ONLY, dry_run=False)

        included.refresh_from_db()
        excluded.refresh_from_db()
        assert included.last_name == "Piloted"
        assert excluded.last_name is None, "outside the pilot list, untouched"

    def test_the_api_key_is_never_in_the_redacted_settings(self):
        from attendees.pcosync.services.config import config_for

        config = config_for(self.organization)
        rendered = config.redacted()
        assert KEY not in str(rendered)
        assert rendered["api_key_set"] is True


def _client(mirror):
    from attendees.pcosync.client import PcoMirrorClient

    return PcoMirrorClient(BASE, KEY, session=mirror, sleep=lambda s: None)
