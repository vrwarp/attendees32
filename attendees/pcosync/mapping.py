"""What corresponds to what, in both directions.

Pure: no network, no ORM writes, no clock. Reading and writing are separated
from deciding, so the merge engine can be tested without a database and this
table can be tested without a server.

The one idea that makes the table work is ``compare_key``: **compare on a
normalised form, write the raw value**. ``(626) 555-0134`` and ``+16265550134``
are the same phone number and must not read as a disagreement, but neither side
should have its formatting rewritten by the other. The baseline stores the
normalised form, so it is comparing like with like.

Three mappings are not simple scalars and are worth reading before editing:

* **Birthday** has a sentinel collision. attendees32 records "year unknown" as
  year 1800; Planning Center records it as 1885. Both are translated here, into
  a canonical ``----MM-DD``. Neither sentinel ever reaches the baseline and
  neither system ever sees the other's.
* **baptized / believer** are not columns at all. In attendees32 they are the
  existence of a ``Past`` row of the right ``Category``. The writers hide that
  entirely, so the merge engine sees an ordinary tri-state and needs to know
  nothing about it.
* **Contacts** are one field each rather than four slots. Which slot a number
  sits in carries no meaning, and treating them separately would report a
  slot swap as two conflicts.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Optional

#: attendees32's "the year is not known" sentinel, per the help text on
#: Attendee.estimated_birthday.
LOCAL_UNKNOWN_YEAR = 1800
#: Planning Center's equivalent. Different number, same meaning; translating
#: between them is this module's job and nobody else's.
PCO_UNKNOWN_YEAR = 1885
#: Canonical stand-in for an unknown year. It replaces ``YYYY-`` -- the year
#: *and its separator* -- so the canonical form of an unknown-year birthday is
#: ``----MM-DD``, nine characters, not ten. Reconstructing a real year therefore
#: has to put the dash back; forgetting to is how this first produced
#: ``188503-14``.
UNKNOWN_YEAR_PREFIX = "----"

GENDER_MALE = "MALE"
GENDER_FEMALE = "FEMALE"
GENDER_UNSPECIFIED = "UNSPECIFIED"

#: Both a receive row and a disbeliever row on the same attendee. Not a value:
#: it means the local record contradicts itself, which a sync must report
#: rather than resolve.
CONTRADICTORY = "contradictory"

SLUG_CHINESE_FIRST = "chinese_first_name"
SLUG_CHINESE_LAST = "chinese_last_name"
SLUG_BAPTIZED = "baptized"
SLUG_BELIEVER = "believer"
SLUG_CONGREGATION = "congregation"
SLUG_ATTENDEES_UUID = "attendees_uuid"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def trimmed(value) -> Optional[str]:
    """Empty string and whitespace are absence, not a value."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalise_email(value) -> Optional[str]:
    text = trimmed(value)
    return text.lower() if text else None


def digits_only(value) -> Optional[str]:
    """A comparable phone number: digits, with a US country code dropped.

    ``+1 (626) 555-0134`` and ``6265550134`` are one number written twice; if
    they compared unequal the sync would push each side's formatting at the
    other for ever.
    """
    text = trimmed(value)
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits or None


def compare_ids(value) -> tuple:
    """Sort key that treats numeric ids numerically.

    Planning Center ids are numeric strings, so lexical ordering puts ``10``
    before ``9``. That only matters because a stable order is what stops
    repeated syncs flapping between two equally-valid choices.
    """
    text = str(value or "")
    return (0, int(text), "") if text.isdigit() else (1, 0, text)


def fold_name(value) -> str:
    """A comparison key for a human name.

    Accents folded, punctuation dropped, lowercased -- but **falling back to the
    folded original when nothing Latin survives**. Without that fallback every
    CJK name reduces to the empty string and a whole congregation collapses onto
    one key, which is the opposite of a match.
    """
    text = trimmed(value)
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    latin = re.sub(r"[^a-zA-Z0-9]+", "", stripped).lower()
    if latin:
        return latin
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).lower()


def sorted_or_none(values) -> Optional[list]:
    cleaned = sorted(v for v in (values or []) if v)
    return cleaned or None


# ---------------------------------------------------------------------------
# Birthday: the sentinel translation
# ---------------------------------------------------------------------------

def canonical_birthday_from_pco(raw) -> Optional[str]:
    """``YYYY-MM-DD`` from Planning Center into the canonical form."""
    text = trimmed(raw)
    if not text:
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return None
    year, month, day = match.groups()
    if int(year) == PCO_UNKNOWN_YEAR:
        return f"{UNKNOWN_YEAR_PREFIX}{month}-{day}"
    return f"{year}-{month}-{day}"


def canonical_birthday_to_pco(canonical) -> Optional[str]:
    """The canonical form back into a Planning Center ``birthdate``.

    Returns ``None`` for year- and month-precision values: PCO's field is a full
    date and cannot hold them. That is a limit of the target, not a
    disagreement, and the caller reports it as such rather than as a conflict.
    """
    if not canonical:
        return None
    if canonical.startswith(UNKNOWN_YEAR_PREFIX):
        return f"{PCO_UNKNOWN_YEAR}-{canonical[len(UNKNOWN_YEAR_PREFIX):]}"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", canonical):
        return canonical
    return None


def is_representable_in_pco(canonical) -> bool:
    return canonical is None or canonical_birthday_to_pco(canonical) is not None


def canonical_birthday_from_local(actual, estimated) -> Optional[str]:
    """``actual_birthday`` wins; otherwise read the PartialDate's precision."""
    if actual:
        return actual.isoformat() if hasattr(actual, "isoformat") else str(actual)
    if not estimated:
        return None

    precision = getattr(estimated, "precision", None)
    value = getattr(estimated, "date", None)
    if value is None:
        return trimmed(estimated)

    if precision == 0:  # PartialDate.YEAR
        return f"{value.year:04d}"
    if precision == 1:  # PartialDate.MONTH
        return f"{value.year:04d}-{value.month:02d}"
    if value.year == LOCAL_UNKNOWN_YEAR:
        return f"{UNKNOWN_YEAR_PREFIX}{value.month:02d}-{value.day:02d}"
    return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"


def local_birthday_fields(canonical):
    """``(actual_birthday, estimated_birthday_string)`` for a canonical value.

    Only one of the two is ever set. Leaving both populated would make the next
    read ambiguous, and ``actual_birthday`` silently wins in that case.
    """
    if not canonical:
        return None, None
    if canonical.startswith(UNKNOWN_YEAR_PREFIX):
        return None, f"{LOCAL_UNKNOWN_YEAR:04d}-{canonical[len(UNKNOWN_YEAR_PREFIX):]}"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", canonical):
        year, month, day = (int(part) for part in canonical.split("-"))
        return date(year, month, day), None
    return None, canonical


def is_refinement(coarse, precise) -> bool:
    """Is ``precise`` the same birthday as ``coarse``, only better known?

    ``1998-03`` against ``1998-03-14`` is one person's birthday recorded twice
    with different care, not two claims in conflict. Treating it as a conflict
    would fill the report with rows nobody can act on.
    """
    if not coarse or not precise or coarse == precise:
        return False
    if coarse.startswith(UNKNOWN_YEAR_PREFIX) or precise.startswith(UNKNOWN_YEAR_PREFIX):
        return False
    return len(precise) > len(coarse) and precise.startswith(coarse)


# ---------------------------------------------------------------------------
# Views over each side
# ---------------------------------------------------------------------------

class IncludedIndex:
    """``included[]`` indexed by ``(type, id)``.

    JSON:API returns side-loads as one flat list of mixed types in no promised
    order, so anything that reads them by position is relying on luck.
    """

    def __init__(self, included=None):
        self._by_key = {}
        self._by_type = {}
        for record in included or []:
            key = (record.get("type"), str(record.get("id")))
            self._by_key[key] = record
            self._by_type.setdefault(record.get("type"), []).append(record)

    def get(self, type_name, record_id):
        return self._by_key.get((type_name, str(record_id)))

    def of_type(self, type_name):
        return self._by_type.get(type_name, [])

    def owned_by(self, type_name, person_id):
        """Children pointing back at this person.

        Emails and phone numbers carry ``relationships.person``; the person's
        own relationship block does not list them, so ownership is read from
        the child rather than the parent.
        """
        owned = []
        for record in self.of_type(type_name):
            rel = (record.get("relationships") or {}).get("person") or {}
            data = rel.get("data") or {}
            if str(data.get("id")) == str(person_id):
                owned.append(record)
        return owned


class PcoPersonView:
    """One Planning Center person, plus whatever came side-loaded with it."""

    def __init__(self, resource, included=None, definitions_by_id=None):
        self.resource = resource or {}
        self.index = included if isinstance(included, IncludedIndex) \
            else IncludedIndex(included)
        #: {field_definition_id: slug}, resolved at runtime. Never hardcoded:
        #: the ids differ per organization.
        self.definitions_by_id = definitions_by_id or {}

    @property
    def id(self):
        return str(self.resource.get("id")) if self.resource.get("id") else None

    @property
    def attributes(self):
        return self.resource.get("attributes") or {}

    def custom(self, slug) -> Optional[str]:
        """The value of one custom field, or None when there is no datum.

        An absent datum is genuinely different from ``"false"``: Planning Center
        deletes the row when a checkbox is cleared, so "never set" and
        "unchecked" arrive identically, and only "set to false" is distinct.
        """
        for datum in self.field_data():
            definition_id = str(
                (((datum.get("relationships") or {}).get("field_definition") or {})
                 .get("data") or {}).get("id") or ""
            )
            if self.definitions_by_id.get(definition_id) == slug:
                return (datum.get("attributes") or {}).get("value")
        return None

    def field_datum_id(self, slug) -> Optional[str]:
        for datum in self.field_data():
            definition_id = str(
                (((datum.get("relationships") or {}).get("field_definition") or {})
                 .get("data") or {}).get("id") or ""
            )
            if self.definitions_by_id.get(definition_id) == slug:
                return str(datum.get("id"))
        return None

    def field_data(self):
        data = []
        for datum in self.index.of_type("FieldDatum"):
            customizable = (((datum.get("relationships") or {}).get("customizable")
                             or {}).get("data") or {})
            if customizable.get("type") == "Person" \
                    and str(customizable.get("id")) == self.id:
                data.append(datum)
        return data

    def contacts(self, type_name, attribute):
        """Values of a contact type, primary first then by id.

        A stable order matters more than the specific order: it is what stops
        two runs disagreeing about which of two emails is "first".
        """
        records = self.index.owned_by(type_name, self.id)
        records.sort(key=lambda r: (
            not (r.get("attributes") or {}).get("primary", False),
            compare_ids(r.get("id")),
        ))
        return [
            (r.get("attributes") or {}).get(attribute)
            for r in records
            if (r.get("attributes") or {}).get(attribute)
        ]

    def household_ids(self):
        rel = (self.resource.get("relationships") or {}).get("households") or {}
        data = rel.get("data") or []
        if isinstance(data, dict):
            data = [data]
        return [str(item.get("id")) for item in data if item.get("id")]


class LocalPersonView:
    """One ``Attendee``, plus the status rows the mapping treats as fields.

    ``status_flags`` is passed in rather than queried so this class stays
    testable without a database, and so a caller sweeping a whole organization
    can fetch every ``Past`` row in one query instead of one per attendee.
    """

    def __init__(self, attendee, status_flags=None, config=None):
        self.attendee = attendee
        #: {"baptized": True/False/None, "believer": ...}
        self.status_flags = status_flags or {}
        self.config = config
        #: Filled by write_local; the caller applies them.
        self.pending_status = {}
        self.dirty = False

    @property
    def infos(self):
        if self.attendee.infos is None:
            self.attendee.infos = {}
        return self.attendee.infos

    def contact(self, *keys):
        contacts = self.infos.get("contacts") or {}
        return [contacts.get(key) for key in keys if contacts.get(key)]

    def set_contacts(self, prefix, values):
        """Fill ``prefix1``/``prefix2`` without disturbing anything else."""
        infos = dict(self.infos)
        contacts = dict(infos.get("contacts") or {})
        values = list(values or [])
        for index in (1, 2):
            key = f"{prefix}{index}"
            value = values[index - 1] if len(values) >= index else None
            if value:
                contacts[key] = value
            else:
                contacts.pop(key, None)
        infos["contacts"] = contacts
        self.attendee.infos = infos
        self.dirty = True


# ---------------------------------------------------------------------------
# The field table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FieldMap:
    key: str
    label: str
    pointer: str
    read_pco: Callable[[PcoPersonView], Any]
    read_local: Callable[[LocalPersonView], Any]
    write_pco: Optional[Callable] = None
    write_local: Optional[Callable] = None
    compare_key: Callable[[Any], Any] = staticmethod(lambda v: v)
    max_local_length: Optional[int] = None
    #: Which custom-field slug this writes, if any.
    slug: Optional[str] = None

    def fits_locally(self, value) -> bool:
        if self.max_local_length is None or value is None:
            return True
        return len(str(value)) <= self.max_local_length


def _write_attr(name):
    def writer(view, value):
        setattr(view.attendee, name, value)
        view.dirty = True
    return writer


def _gender_from_pco(view):
    return normalise_gender(view.attributes.get("gender"))


def normalise_gender(raw):
    """Fold whatever is in the column onto MALE / FEMALE / UNSPECIFIED.

    ``GenderEnum.choices()`` yields ``(name, value)``, so Django stores the
    *name* and the seed data holds ``"MALE"``. But the model's default is the
    enum member itself and some older code writes ``GenderEnum.MALE.value``, so
    a real database contains ``"male"`` too. Reading only the canonical spelling
    would make every such attendee disagree with Planning Center about a field
    nobody had touched.
    """
    text = trimmed(raw)
    if not text:
        return GENDER_UNSPECIFIED
    text = text.rsplit(".", 1)[-1].upper()  # also survives "GenderEnum.MALE"
    if text.startswith("M"):
        return GENDER_MALE
    if text.startswith("F"):
        return GENDER_FEMALE
    return GENDER_UNSPECIFIED


def _gender_compare(value):
    """UNSPECIFIED compares as absence.

    It is the model default, so every attendee "holds" it without anybody
    having said so. Comparing it as a value would make the first run report a
    gender conflict for every person in the organization.
    """
    normalised = normalise_gender(value)
    return None if normalised == GENDER_UNSPECIFIED else normalised


def _write_gender_local(view, value):
    # Store the canonical name, which is what GenderEnum.choices() declares and
    # what the seed data holds.
    view.attendee.gender = normalise_gender(value)
    view.dirty = True


def _write_gender_pco(batch, value):
    upstream = {GENDER_MALE: "Male",
                GENDER_FEMALE: "Female"}.get(normalise_gender(value))
    # Never send a null. "We do not know" is not a fact worth pushing, and
    # sending it would clear whatever Planning Center had.
    if upstream:
        batch.set_attribute("gender", upstream)


def _birthday_from_local(view):
    return canonical_birthday_from_local(
        view.attendee.actual_birthday, view.attendee.estimated_birthday
    )


def _write_birthday_local(view, value):
    actual, estimated = local_birthday_fields(value)
    view.attendee.actual_birthday = actual
    view.attendee.estimated_birthday = estimated
    view.dirty = True


def _write_birthday_pco(batch, value):
    representable = canonical_birthday_to_pco(value)
    if representable is None and value is not None:
        batch.not_representable("birthday", value)
        return
    batch.set_attribute("birthdate", representable)


def _status_reader(name):
    def reader(view):
        return view.status_flags.get(name)
    return reader


def _status_writer(name):
    def writer(view, value):
        # Only an affirmative creates a row. Neither None nor False deletes one:
        # a sync does not clear, and soft-deleting somebody's baptism record is
        # not a decision this code gets to make.
        if value is True:
            view.pending_status[name] = True
    return writer


def _custom_string_writer(slug):
    def writer(batch, value):
        batch.set_custom(slug, value)
    return writer


def _boolean_custom_writer(slug):
    def writer(batch, value):
        if value is None:
            return
        # PATCH to "false" rather than deleting the datum: deleting would throw
        # away the affirmative negative and make the field unreadable next pull.
        batch.set_custom(slug, "true" if value else "false")
    return writer


def _boolean_from_custom(view, slug):
    raw = trimmed(view.custom(slug))
    if raw is None:
        return None
    return raw.lower() in ("true", "1", "yes")


def _congregation_from_local(view):
    division = getattr(view.attendee, "division", None)
    division_id = getattr(division, "id", None)
    # Division 0 is the on_delete=SET(0) sentinel, so it means "unset", exactly
    # like an UNSPECIFIED gender does.
    if division_id in (None, 0):
        return None
    if not view.config:
        return None
    return view.config.division_id_to_congregation.get(int(division_id))


PERSON_FIELDS = (
    FieldMap(
        key="first_name", label="First name", pointer="$.person.first_name",
        read_pco=lambda v: trimmed(v.attributes.get("first_name")),
        read_local=lambda v: trimmed(v.attendee.first_name),
        write_local=_write_attr("first_name"),
        write_pco=lambda b, value: b.set_attribute("first_name", value),
        max_local_length=25,
    ),
    FieldMap(
        key="last_name", label="Last name", pointer="$.person.last_name",
        read_pco=lambda v: trimmed(v.attributes.get("last_name")),
        read_local=lambda v: trimmed(v.attendee.last_name),
        write_local=_write_attr("last_name"),
        write_pco=lambda b, value: b.set_attribute("last_name", value),
        max_local_length=25,
    ),
    FieldMap(
        key="first_name2", label="Chinese first name",
        pointer="$.person.chinese_first_name", slug=SLUG_CHINESE_FIRST,
        read_pco=lambda v: trimmed(v.custom(SLUG_CHINESE_FIRST)),
        read_local=lambda v: trimmed(v.attendee.first_name2),
        write_local=_write_attr("first_name2"),
        write_pco=_custom_string_writer(SLUG_CHINESE_FIRST),
        max_local_length=12,
    ),
    FieldMap(
        key="last_name2", label="Chinese last name",
        pointer="$.person.chinese_last_name", slug=SLUG_CHINESE_LAST,
        read_pco=lambda v: trimmed(v.custom(SLUG_CHINESE_LAST)),
        read_local=lambda v: trimmed(v.attendee.last_name2),
        write_local=_write_attr("last_name2"),
        write_pco=_custom_string_writer(SLUG_CHINESE_LAST),
        max_local_length=8,
    ),
    FieldMap(
        key="gender", label="Gender", pointer="$.person.gender",
        read_pco=_gender_from_pco,
        read_local=lambda v: trimmed(v.attendee.gender) or GENDER_UNSPECIFIED,
        write_local=_write_gender_local,
        write_pco=_write_gender_pco,
        compare_key=_gender_compare,
    ),
    FieldMap(
        key="birthday", label="Birthday", pointer="$.person.birthdate",
        read_pco=lambda v: canonical_birthday_from_pco(v.attributes.get("birthdate")),
        read_local=_birthday_from_local,
        write_local=_write_birthday_local,
        write_pco=_write_birthday_pco,
    ),
    FieldMap(
        key="emails", label="Email addresses", pointer="$.person.emails",
        read_pco=lambda v: sorted_or_none(
            normalise_email(a) for a in v.contacts("Email", "address")
        ),
        read_local=lambda v: sorted_or_none(
            normalise_email(a) for a in v.contact("email1", "email2")
        ),
        write_local=lambda v, value: v.set_contacts("email", value),
        write_pco=lambda b, value: b.add_contacts("Email", "address", value),
        compare_key=lambda v: sorted_or_none(normalise_email(a) for a in (v or [])),
    ),
    FieldMap(
        key="phones", label="Phone numbers", pointer="$.person.phone_numbers",
        read_pco=lambda v: sorted_or_none(v.contacts("PhoneNumber", "number")),
        read_local=lambda v: sorted_or_none(v.contact("phone1", "phone2")),
        write_local=lambda v, value: v.set_contacts("phone", value),
        write_pco=lambda b, value: b.add_contacts("PhoneNumber", "number", value),
        compare_key=lambda v: sorted_or_none(digits_only(n) for n in (v or [])),
    ),
    FieldMap(
        key="congregation", label="Congregation",
        pointer="$.person.congregation", slug=SLUG_CONGREGATION,
        read_pco=lambda v: trimmed(v.custom(SLUG_CONGREGATION)),
        read_local=_congregation_from_local,
        write_local=None,  # applied by the service, which owns the Division FK
        write_pco=_custom_string_writer(SLUG_CONGREGATION),
    ),
    FieldMap(
        key="baptized", label="Baptized", pointer="$.person.baptized",
        slug=SLUG_BAPTIZED,
        read_pco=lambda v: _boolean_from_custom(v, SLUG_BAPTIZED),
        read_local=_status_reader("baptized"),
        write_local=_status_writer("baptized"),
        write_pco=_boolean_custom_writer(SLUG_BAPTIZED),
    ),
    FieldMap(
        key="believer", label="Believer", pointer="$.person.believer",
        slug=SLUG_BELIEVER,
        read_pco=lambda v: _boolean_from_custom(v, SLUG_BELIEVER),
        read_local=_status_reader("believer"),
        write_local=_status_writer("believer"),
        write_pco=_boolean_custom_writer(SLUG_BELIEVER),
        # A local record holding both "receive" and "disbeliever" contradicts
        # itself. Comparing that against a boolean would be meaningless, so it
        # is reported and the field is skipped in both directions.
        compare_key=lambda v: CONTRADICTORY if v == CONTRADICTORY else v,
    ),
)

FIELDS_BY_KEY = {field.key: field for field in PERSON_FIELDS}

#: The join key, kept out of PERSON_FIELDS on purpose. It is never merged and
#: never read back into attendees32 -- it is how the two systems find each
#: other, and its value is simply the attendee's primary key.
ATTENDEES_UUID = FieldMap(
    key="attendees_uuid", label="Attendees UUID",
    pointer="$.person.attendees_uuid", slug=SLUG_ATTENDEES_UUID,
    read_pco=lambda v: trimmed(v.custom(SLUG_ATTENDEES_UUID)),
    read_local=lambda v: str(v.attendee.id),
    write_local=None,
    write_pco=_custom_string_writer(SLUG_ATTENDEES_UUID),
)


class PcoWriteBatch:
    """What a set of decisions wants done to one Planning Center person.

    Collected rather than performed, for two reasons. It lets a dry run produce
    exactly the same plan as a real run without touching anything -- the plan
    *is* the deliverable on day one. And it coalesces every attribute change
    into a single PATCH, which matters because each separate request is another
    chance to half-apply a person.
    """

    def __init__(self, pco_person_id=None, field_datum_ids=None):
        self.pco_person_id = pco_person_id
        self.attributes = {}
        #: {slug: value}. Turned into field_data POSTs or PATCHes by the caller,
        #: which knows the definition ids and the existing datum ids.
        self.custom_fields = {}
        #: Contacts are add-only, so these are only ever things to create.
        self.contacts = []
        #: Values that simply cannot be stored upstream. Not conflicts.
        self.unrepresentable = []
        self.existing_datum_ids = dict(field_datum_ids or {})

    def set_attribute(self, name, value):
        self.attributes[name] = value

    def set_custom(self, slug, value):
        self.custom_fields[slug] = value

    def add_contacts(self, type_name, attribute, values):
        """Queue contacts that are missing upstream.

        Add-only, deliberately. A value already on file is left alone and
        reported as skipped, which is exactly what makes a retry safe: a second
        attempt writes only what is still missing.
        """
        for value in values or []:
            self.contacts.append({"type": type_name, "attribute": attribute,
                                  "value": value})

    def not_representable(self, key, value):
        self.unrepresentable.append({"key": key, "value": value})

    @property
    def is_empty(self):
        return not (self.attributes or self.custom_fields or self.contacts)

    def person_payload(self):
        if not self.attributes:
            return None
        payload = {"type": "Person", "attributes": dict(self.attributes)}
        if self.pco_person_id:
            payload["id"] = str(self.pco_person_id)
        return {"data": payload}


def match_key(first_name, last_name, first_name2, last_name2, birthday=None):
    """A comparable identity for fuzzy matching, never for joining.

    Two people can share this key -- siblings with the same birthday and a
    transposed name would -- so it ranks candidates for a human to choose
    between. It is not a join, and nothing links on it automatically.
    """
    latin = f"{fold_name(first_name)}|{fold_name(last_name)}"
    cjk = f"{fold_name(first_name2)}|{fold_name(last_name2)}"
    return f"{latin}|{cjk}|{birthday or ''}"
