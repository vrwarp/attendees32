"""Round-trips through the field table.

The assertion that matters most is that a value survives a trip in either
direction unchanged. A mapping that loses precision, or that lets one system's
sentinel leak into the other, produces a sync that quietly rewrites real
people's birthdays -- and does it consistently enough to look deliberate.

No database: ``LocalPersonView`` reads a plain object, so these run in a bare
interpreter alongside the merge tests.
"""

from datetime import date

import pytest
from partial_date import PartialDate

from attendees.pcosync.mapping import (
    CONTRADICTORY,
    FIELDS_BY_KEY,
    GENDER_FEMALE,
    GENDER_MALE,
    GENDER_UNSPECIFIED,
    LOCAL_UNKNOWN_YEAR,
    PCO_UNKNOWN_YEAR,
    PERSON_FIELDS,
    IncludedIndex,
    LocalPersonView,
    PcoPersonView,
    PcoWriteBatch,
    canonical_birthday_from_local,
    canonical_birthday_from_pco,
    canonical_birthday_to_pco,
    compare_ids,
    digits_only,
    fold_name,
    is_refinement,
    is_representable_in_pco,
    local_birthday_fields,
    match_key,
)
from attendees.pcosync.merge import decide

DEFINITIONS = {
    "100001": "chinese_last_name",
    "100002": "chinese_first_name",
    "100003": "baptized",
    "100004": "believer",
    "100005": "congregation",
    "100006": "attendees_uuid",
}


class FakeDivision:
    def __init__(self, division_id):
        self.id = division_id


class FakeAttendee:
    """Just the fields the mapping touches."""

    def __init__(self, **kwargs):
        self.id = kwargs.pop("id", "49874dab-4135-4949-b053-b6d1b263489f")
        self.first_name = kwargs.pop("first_name", None)
        self.last_name = kwargs.pop("last_name", None)
        self.first_name2 = kwargs.pop("first_name2", None)
        self.last_name2 = kwargs.pop("last_name2", None)
        self.gender = kwargs.pop("gender", GENDER_UNSPECIFIED)
        self.actual_birthday = kwargs.pop("actual_birthday", None)
        self.estimated_birthday = kwargs.pop("estimated_birthday", None)
        self.division = kwargs.pop("division", None)
        self.infos = kwargs.pop("infos", None) or {"contacts": {}, "names": {}}


class FakeConfig:
    def __init__(self, congregation_to_division_id=None):
        self.congregation_to_division_id = congregation_to_division_id or {}

    @property
    def division_id_to_congregation(self):
        return {int(v): k for k, v in self.congregation_to_division_id.items()}


def pco_view(attributes=None, custom=None, emails=(), phones=(), person_id="900"):
    included = []
    for index, (slug, value) in enumerate(sorted((custom or {}).items())):
        definition_id = next(k for k, v in DEFINITIONS.items() if v == slug)
        included.append({
            "type": "FieldDatum", "id": f"5{index}",
            "attributes": {"value": value},
            "relationships": {
                "field_definition": {"data": {"type": "FieldDefinition",
                                              "id": definition_id}},
                "customizable": {"data": {"type": "Person", "id": person_id}},
            },
        })
    for index, address in enumerate(emails):
        included.append({
            "type": "Email", "id": f"7{index}",
            "attributes": {"address": address, "primary": index == 0},
            "relationships": {"person": {"data": {"type": "Person", "id": person_id}}},
        })
    for index, number in enumerate(phones):
        included.append({
            "type": "PhoneNumber", "id": f"8{index}",
            "attributes": {"number": number, "primary": index == 0},
            "relationships": {"person": {"data": {"type": "Person", "id": person_id}}},
        })
    return PcoPersonView(
        {"type": "Person", "id": person_id, "attributes": attributes or {}},
        included, DEFINITIONS,
    )


def local_view(**kwargs):
    status = kwargs.pop("status_flags", None)
    config = kwargs.pop("config", None)
    return LocalPersonView(FakeAttendee(**kwargs), status, config)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("+1 (626) 555-0134", "6265550134"),
    ("(626) 555-0134", "6265550134"),
    ("626.555.0134", "6265550134"),
    ("16265550134", "6265550134"),
    ("", None),
    (None, None),
])
def test_phone_numbers_compare_by_digits(raw, expected):
    assert digits_only(raw) == expected


def test_a_non_us_number_keeps_its_leading_digits():
    """Only an 11-digit number starting 1 loses it; +44 must survive intact."""
    assert digits_only("+44 20 7946 0958") == "442079460958"


def test_fold_name_strips_accents_and_punctuation():
    assert fold_name("Chloë O'Brien-Smith") == "chloeobriensmith"


def test_fold_name_keeps_cjk_rather_than_collapsing_it():
    """The fallback that stops a whole congregation sharing one key."""
    assert fold_name("蔡秉洲") == "蔡秉洲"
    assert fold_name("蔡秉洲") != fold_name("林國樑")


def test_fold_name_of_nothing_is_empty():
    assert fold_name(None) == ""
    assert fold_name("   ") == ""


def test_compare_ids_orders_numerically():
    assert sorted(["10", "9", "100"], key=compare_ids) == ["9", "10", "100"]


def test_match_key_distinguishes_two_people_with_the_same_latin_name():
    left = match_key("Ben", "Tsai", "秉洲", "蔡", "1998-03-14")
    right = match_key("Ben", "Tsai", "國樑", "林", "1998-03-14")
    assert left != right


# ---------------------------------------------------------------------------
# Birthday: the sentinel collision
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("canonical", [
    "1992-12-31", "----03-14", "1998-12", "1998", None,
])
def test_birthday_round_trips_through_attendees32(canonical):
    actual, estimated = local_birthday_fields(canonical)
    estimated = PartialDate(estimated) if estimated else None
    assert canonical_birthday_from_local(actual, estimated) == canonical


@pytest.mark.parametrize("canonical", ["1992-12-31", "----03-14", None])
def test_birthday_round_trips_through_planning_center(canonical):
    assert canonical_birthday_from_pco(canonical_birthday_to_pco(canonical)) == canonical


def test_pcos_unknown_year_becomes_the_canonical_marker():
    assert canonical_birthday_from_pco(f"{PCO_UNKNOWN_YEAR}-03-14") == "----03-14"


def test_attendees32s_unknown_year_becomes_the_same_marker():
    estimated = PartialDate(f"{LOCAL_UNKNOWN_YEAR}-03-14")
    assert canonical_birthday_from_local(None, estimated) == "----03-14"


def test_the_two_sentinels_never_meet():
    """1800 must never reach Planning Center and 1885 must never reach us."""
    from_local = canonical_birthday_from_local(
        None, PartialDate(f"{LOCAL_UNKNOWN_YEAR}-03-14")
    )
    assert str(LOCAL_UNKNOWN_YEAR) not in canonical_birthday_to_pco(from_local)

    from_pco = canonical_birthday_from_pco(f"{PCO_UNKNOWN_YEAR}-03-14")
    _, estimated = local_birthday_fields(from_pco)
    assert str(PCO_UNKNOWN_YEAR) not in estimated
    assert estimated.startswith(str(LOCAL_UNKNOWN_YEAR))


def test_neither_sentinel_reaches_the_baseline():
    view = pco_view({"birthdate": f"{PCO_UNKNOWN_YEAR}-03-14"})
    canonical = FIELDS_BY_KEY["birthday"].read_pco(view)
    assert canonical == "----03-14"
    assert str(PCO_UNKNOWN_YEAR) not in canonical
    assert str(LOCAL_UNKNOWN_YEAR) not in canonical


@pytest.mark.parametrize("canonical", ["1998", "1998-12"])
def test_a_partial_birthday_cannot_be_stored_upstream(canonical):
    assert canonical_birthday_to_pco(canonical) is None
    assert is_representable_in_pco(canonical) is False


def test_a_full_birthday_is_representable():
    assert is_representable_in_pco("1992-12-31") is True
    assert is_representable_in_pco(None) is True


def test_an_unrepresentable_value_is_recorded_rather_than_pushed():
    batch = PcoWriteBatch("900")
    FIELDS_BY_KEY["birthday"].write_pco(batch, "1998-12")
    assert batch.attributes == {}
    assert batch.unrepresentable == [{"key": "birthday", "value": "1998-12"}]


def test_a_more_precise_birthday_is_a_refinement_not_a_conflict():
    assert is_refinement("1998-03", "1998-03-14") is True
    assert is_refinement("1998", "1998-03") is True


def test_a_different_birthday_is_not_a_refinement():
    assert is_refinement("1998-03", "1998-04-14") is False
    assert is_refinement("1998-03-14", "1998-03") is False
    assert is_refinement("----03-14", "1998-03-14") is False


def test_actual_birthday_wins_over_an_estimate():
    view = local_view(actual_birthday=date(1992, 12, 31),
                      estimated_birthday=PartialDate("1990"))
    assert FIELDS_BY_KEY["birthday"].read_local(view) == "1992-12-31"


def test_writing_a_birthday_clears_the_other_column():
    """Leaving both set makes the next read ambiguous."""
    view = local_view(estimated_birthday=PartialDate("1990"))
    FIELDS_BY_KEY["birthday"].write_local(view, "1992-12-31")
    assert view.attendee.actual_birthday == date(1992, 12, 31)
    assert view.attendee.estimated_birthday is None

    FIELDS_BY_KEY["birthday"].write_local(view, "1998")
    assert view.attendee.actual_birthday is None
    assert view.attendee.estimated_birthday == "1998"


# ---------------------------------------------------------------------------
# Gender
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Male", GENDER_MALE), ("M", GENDER_MALE),
    ("Female", GENDER_FEMALE), ("F", GENDER_FEMALE),
    (None, GENDER_UNSPECIFIED), ("", GENDER_UNSPECIFIED),
    ("Other", GENDER_UNSPECIFIED),
])
def test_gender_reads_from_planning_center(raw, expected):
    assert FIELDS_BY_KEY["gender"].read_pco(pco_view({"gender": raw})) == expected


def test_unspecified_gender_compares_as_absence():
    """Otherwise every attendee conflicts on gender during the first run."""
    field = FIELDS_BY_KEY["gender"]
    assert field.compare_key(GENDER_UNSPECIFIED) is None
    assert field.compare_key(GENDER_MALE) == GENDER_MALE

    local = local_view(gender=GENDER_UNSPECIFIED)
    remote = pco_view({"gender": "Male"})
    decision = decide(field, field.read_local(local), field.read_pco(remote), {})
    assert decision.outcome == "to_local"  # a first fill, not a disagreement


def test_gender_round_trips():
    for value in (GENDER_MALE, GENDER_FEMALE):
        batch = PcoWriteBatch("900")
        FIELDS_BY_KEY["gender"].write_pco(batch, value)
        view = pco_view({"gender": batch.attributes["gender"]})
        assert FIELDS_BY_KEY["gender"].read_pco(view) == value


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def test_chinese_names_come_from_the_custom_field_tab():
    view = pco_view(custom={"chinese_first_name": "秉洲", "chinese_last_name": "蔡"})
    assert FIELDS_BY_KEY["first_name2"].read_pco(view) == "秉洲"
    assert FIELDS_BY_KEY["last_name2"].read_pco(view) == "蔡"


def test_a_blank_custom_field_reads_as_absent_not_as_empty_string():
    view = pco_view(custom={"chinese_first_name": "   "})
    assert FIELDS_BY_KEY["first_name2"].read_pco(view) is None


@pytest.mark.parametrize("key,limit", [
    ("first_name", 25), ("last_name", 25), ("first_name2", 12), ("last_name2", 8),
])
def test_name_length_limits_are_declared_so_overflow_can_be_refused(key, limit):
    field = FIELDS_BY_KEY[key]
    assert field.max_local_length == limit
    assert field.fits_locally("x" * limit) is True
    assert field.fits_locally("x" * (limit + 1)) is False
    assert field.fits_locally(None) is True


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

def test_emails_are_one_field_and_compare_case_insensitively():
    field = FIELDS_BY_KEY["emails"]
    remote = pco_view(emails=["Ann@Example.COM"])
    local = local_view(infos={"contacts": {"email1": "ann@example.com"}})
    assert decide(field, field.read_local(local), field.read_pco(remote), {}).outcome \
        == "agree"


def test_a_slot_swap_is_not_a_disagreement():
    """Which slot a number sits in carries no meaning."""
    field = FIELDS_BY_KEY["phones"]
    local_a = local_view(infos={"contacts": {"phone1": "6265550134",
                                             "phone2": "5105550199"}})
    local_b = local_view(infos={"contacts": {"phone1": "5105550199",
                                             "phone2": "6265550134"}})
    assert field.compare_key(field.read_local(local_a)) \
        == field.compare_key(field.read_local(local_b))


def test_differently_formatted_phone_numbers_agree():
    field = FIELDS_BY_KEY["phones"]
    remote = pco_view(phones=["(626) 555-0134"])
    local = local_view(infos={"contacts": {"phone1": "+16265550134"}})
    assert decide(field, field.read_local(local), field.read_pco(remote), {}).outcome \
        == "agree"


def test_a_primary_email_is_read_first():
    view = PcoPersonView(
        {"type": "Person", "id": "900", "attributes": {}},
        [
            {"type": "Email", "id": "2", "attributes": {"address": "second@x.com",
                                                        "primary": False},
             "relationships": {"person": {"data": {"type": "Person", "id": "900"}}}},
            {"type": "Email", "id": "1", "attributes": {"address": "first@x.com",
                                                        "primary": True},
             "relationships": {"person": {"data": {"type": "Person", "id": "900"}}}},
        ],
        DEFINITIONS,
    )
    assert view.contacts("Email", "address")[0] == "first@x.com"


def test_contacts_belonging_to_another_person_are_ignored():
    view = PcoPersonView(
        {"type": "Person", "id": "900", "attributes": {}},
        [{"type": "Email", "id": "1",
          "attributes": {"address": "someone.else@x.com", "primary": True},
          "relationships": {"person": {"data": {"type": "Person", "id": "901"}}}}],
        DEFINITIONS,
    )
    assert view.contacts("Email", "address") == []


def test_writing_contacts_locally_fills_both_slots_and_clears_the_spare():
    view = local_view(infos={"contacts": {"email1": "a@x.com", "email2": "b@x.com"}})
    FIELDS_BY_KEY["emails"].write_local(view, ["only@x.com"])
    assert view.attendee.infos["contacts"] == {"email1": "only@x.com"}


def test_writing_contacts_leaves_unrelated_infos_alone():
    view = local_view(infos={"contacts": {"phone1": "6265550134"},
                             "names": {"original": "Ann Lee"}})
    FIELDS_BY_KEY["emails"].write_local(view, ["ann@x.com"])
    assert view.attendee.infos["contacts"]["phone1"] == "6265550134"
    assert view.attendee.infos["names"]["original"] == "Ann Lee"


def test_contacts_are_added_upstream_never_replaced():
    batch = PcoWriteBatch("900")
    FIELDS_BY_KEY["emails"].write_pco(batch, ["new@x.com"])
    assert batch.contacts == [{"type": "Email", "attribute": "address",
                               "value": "new@x.com"}]
    assert batch.attributes == {}


# ---------------------------------------------------------------------------
# Row-existence mappings
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("false", False), (None, None),
])
def test_a_boolean_custom_field_reads_as_a_tri_state(raw, expected):
    custom = {"baptized": raw} if raw is not None else {}
    assert FIELDS_BY_KEY["baptized"].read_pco(pco_view(custom=custom)) is expected


def test_an_absent_datum_is_not_the_same_as_false():
    """PCO deletes the datum when a box is cleared, so absence is ambiguous."""
    assert FIELDS_BY_KEY["baptized"].read_pco(pco_view(custom={})) is None
    assert FIELDS_BY_KEY["baptized"].read_pco(pco_view(custom={"baptized": "false"})) \
        is False


def test_baptized_reads_from_a_past_row_existing():
    assert FIELDS_BY_KEY["baptized"].read_local(
        local_view(status_flags={"baptized": True})) is True
    assert FIELDS_BY_KEY["baptized"].read_local(local_view()) is None


def test_writing_baptized_true_queues_a_past_row():
    view = local_view()
    FIELDS_BY_KEY["baptized"].write_local(view, True)
    assert view.pending_status == {"baptized": True}


@pytest.mark.parametrize("value", [False, None])
def test_nothing_ever_deletes_a_status_row(value):
    """Soft-deleting somebody's baptism record is not a sync's decision."""
    view = local_view(status_flags={"baptized": True})
    FIELDS_BY_KEY["baptized"].write_local(view, value)
    assert view.pending_status == {}


def test_a_false_boolean_is_patched_rather_than_deleted_upstream():
    """Deleting the datum would lose the affirmative negative."""
    batch = PcoWriteBatch("900")
    FIELDS_BY_KEY["believer"].write_pco(batch, False)
    assert batch.custom_fields == {"believer": "false"}


def test_a_none_boolean_writes_nothing_upstream():
    batch = PcoWriteBatch("900")
    FIELDS_BY_KEY["believer"].write_pco(batch, None)
    assert batch.custom_fields == {}


def test_a_contradictory_local_record_never_agrees_with_anything():
    field = FIELDS_BY_KEY["believer"]
    decision = decide(field, CONTRADICTORY, True, {})
    assert decision.outcome == "conflict"


def test_a_status_that_is_true_on_both_sides_agrees():
    field = FIELDS_BY_KEY["believer"]
    local = local_view(status_flags={"believer": True})
    remote = pco_view(custom={"believer": "true"})
    assert decide(field, field.read_local(local), field.read_pco(remote), {}).outcome \
        == "agree"


# ---------------------------------------------------------------------------
# Congregation
# ---------------------------------------------------------------------------

def test_congregation_maps_to_a_division_through_config():
    config = FakeConfig({"Children": 3, "Chinese": 1})
    view = local_view(division=FakeDivision(3), config=config)
    assert FIELDS_BY_KEY["congregation"].read_local(view) == "Children"


def test_division_zero_is_the_sentinel_and_reads_as_absent():
    config = FakeConfig({"Children": 3})
    view = local_view(division=FakeDivision(0), config=config)
    assert FIELDS_BY_KEY["congregation"].read_local(view) is None


def test_an_unmapped_division_reads_as_absent_rather_than_guessing():
    config = FakeConfig({"Children": 3})
    view = local_view(division=FakeDivision(99), config=config)
    assert FIELDS_BY_KEY["congregation"].read_local(view) is None


def test_congregation_is_never_written_directly_to_the_attendee():
    """The Division FK belongs to the service, which validates it exists."""
    assert FIELDS_BY_KEY["congregation"].write_local is None


# ---------------------------------------------------------------------------
# The join key
# ---------------------------------------------------------------------------

def test_attendees_uuid_is_not_a_merged_field():
    assert "attendees_uuid" not in FIELDS_BY_KEY


def test_attendees_uuid_reads_the_attendee_primary_key():
    from attendees.pcosync.mapping import ATTENDEES_UUID

    view = local_view(id="49874dab-4135-4949-b053-b6d1b263489f")
    assert ATTENDEES_UUID.read_local(view) == "49874dab-4135-4949-b053-b6d1b263489f"
    assert ATTENDEES_UUID.write_local is None


def test_attendees_uuid_reads_back_from_the_custom_field():
    from attendees.pcosync.mapping import ATTENDEES_UUID

    view = pco_view(custom={"attendees_uuid": "49874dab-4135-4949-b053-b6d1b263489f"})
    assert ATTENDEES_UUID.read_pco(view) == "49874dab-4135-4949-b053-b6d1b263489f"


# ---------------------------------------------------------------------------
# The table as a whole
# ---------------------------------------------------------------------------

def test_every_field_has_a_unique_key_and_pointer():
    keys = [f.key for f in PERSON_FIELDS]
    pointers = [f.pointer for f in PERSON_FIELDS]
    assert len(keys) == len(set(keys))
    assert len(pointers) == len(set(pointers))


def test_every_field_can_be_read_from_both_sides():
    for field in PERSON_FIELDS:
        assert callable(field.read_pco), field.key
        assert callable(field.read_local), field.key


def test_every_field_can_be_written_somewhere():
    """A field readable in both directions but writable in neither is dead weight."""
    for field in PERSON_FIELDS:
        assert field.write_local or field.write_pco, field.key


def test_reading_an_empty_person_yields_no_values_and_no_crash():
    view = pco_view()
    local = local_view(config=FakeConfig())
    for field in PERSON_FIELDS:
        assert field.compare_key(field.read_pco(view)) is None, field.key
        assert field.compare_key(field.read_local(local)) is None, field.key


def test_two_empty_sides_agree_on_every_field():
    remote, local = pco_view(), local_view(config=FakeConfig())
    for field in PERSON_FIELDS:
        decision = decide(field, field.read_local(local), field.read_pco(remote), {})
        assert decision.outcome == "agree", field.key


def test_a_batch_coalesces_attributes_into_one_payload():
    batch = PcoWriteBatch("900")
    FIELDS_BY_KEY["first_name"].write_pco(batch, "Ann")
    FIELDS_BY_KEY["last_name"].write_pco(batch, "Lee")
    payload = batch.person_payload()
    assert payload == {"data": {"type": "Person", "id": "900",
                                "attributes": {"first_name": "Ann",
                                               "last_name": "Lee"}}}


def test_an_empty_batch_has_no_payload():
    assert PcoWriteBatch("900").is_empty is True
    assert PcoWriteBatch("900").person_payload() is None


def test_an_included_index_finds_records_by_type_and_id():
    index = IncludedIndex([{"type": "Email", "id": "1", "attributes": {}}])
    assert index.get("Email", "1") is not None
    assert index.get("Email", 1) is not None  # int or str, same record
    assert index.get("PhoneNumber", "1") is None
