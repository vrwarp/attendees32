"""One sync run, phase by phase.

The order is deliberate: local writes land before any upstream write, so a
failure in the second half leaves the first half consistent with the baseline
rather than half-agreed with a Planning Center that never heard about it.

Everything is budgeted, and every budget defaults to zero or off. A
freshly-configured organization produces a full report and writes nothing.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from attendees.persons.models import Attendee, Past
from attendees.pcosync import mapping, merge
from attendees.pcosync.client import (
    PcoApiError,
    PcoGoneError,
    PcoMirrorClient,
    PcoNetworkError,
    PcoWriteIndeterminate,
)
from attendees.pcosync.models import PcoDivergence, PcoPersonLink, PcoSyncRun
from attendees.pcosync.services import field_definitions as fielddefs
from attendees.pcosync.services import identity, statuses
from attendees.pcosync.services.config import config_for
from attendees.pcosync.services.divergences import DivergenceRecorder

logger = logging.getLogger(__name__)

#: People hydrated individually when the bulk sweep missed them. Anyone past
#: this is reported, never dropped -- "the sync is behind" and "eight people
#: vanished" must not look the same.
MAX_INDIVIDUAL_LOOKUPS = 200


class SyncAborted(Exception):
    """The run cannot safely continue. Carries a reason a person can act on."""


class Runner:
    """Executes a run. Owns no HTTP behaviour and no merge logic of its own."""

    def __init__(self, run, client=None, now=None):
        self.run = run
        self.organization = run.organization
        self.config = config_for(self.organization)
        self.now = now or timezone.now
        self.client = client or self._build_client()
        self.recorder = DivergenceRecorder(self.organization, run, self.now)
        self.definitions = None
        self.uuid_index = {}
        self.writes_used = 0
        self.creates_used = 0
        self.push_blocked_reason = None

    def _build_client(self):
        reason = self.config.blocking_reason()
        if reason:
            raise SyncAborted(reason)
        return PcoMirrorClient(self.config.base_url, self.config.api_key)

    # -- budgets ----------------------------------------------------------

    @property
    def may_write_upstream(self):
        if not self.run.writes_upstream:
            return False
        if self.config.dry_run or not self.config.push_enabled:
            return False
        if self.push_blocked_reason:
            return False
        return self.writes_used < self.config.max_writes_per_run

    def spend_write(self):
        self.writes_used += 1
        self.run.bump("upstream_writes")

    # -- phases -----------------------------------------------------------

    def resolve_definitions(self):
        self.definitions = fielddefs.resolve(
            self.client, self.organization.id,
            self.config.field_definition_tab_id,
        ).require()
        self.run.bump("field_definitions", len(self.definitions))
        self.check_staleness()
        return self.definitions

    def check_staleness(self):
        """Refuse to push from a stale read.

        A ``to_pco`` decision computed from a day-old mirror is how you
        overwrite an edit somebody made an hour ago. Only possible to check at
        all because the mirror reports its own freshness.
        """
        if not self.run.writes_upstream:
            return
        oldest = self.client.last_mirror_oldest_synced_at
        if not oldest:
            return
        parsed = parse_datetime(oldest)
        if not parsed:
            return
        limit = timedelta(minutes=self.config.max_mirror_staleness_minutes)
        age = self.now() - parsed
        if age > limit:
            self.push_blocked_reason = (
                f"the mirror last synced {oldest}, which is older than the "
                f"{self.config.max_mirror_staleness_minutes} minute limit"
            )
            self.recorder.record(
                PcoDivergence.MIRROR_STALE, "$.mirror.oldest_last_synced_at",
                note=self.push_blocked_reason, severity=PcoDivergence.ERROR,
                pco_value=oldest,
            )

    def build_uuid_index(self):
        definition_id = self.definitions.id_for(mapping.SLUG_ATTENDEES_UUID)
        self.uuid_index = identity.build_uuid_index(self.client, definition_id)
        self.run.bump("uuid_index", len(self.uuid_index))
        return self.uuid_index

    def iter_people(self, offset=0, limit=None):
        """The bulk sweep: one page answers for a hundred people.

        Ordered by ``created_at`` rather than ``updated_at``. Pagination here is
        offset-only, so ordering on a column that changes while you walk lets
        rows shuffle between pages and quietly skip some. ``created_at`` is
        append-only and cannot do that. (``id`` is not in ``can_order_by``.)
        """
        query = {
            "include": ["emails", "phone_numbers", "field_data", "households"],
            "order": "created_at",
            "offset": offset,
        }
        seen = 0
        for page in self.client.paginate("/people", query, per_page=100):
            index = mapping.IncludedIndex(page.included)
            for record in page.data:
                yield mapping.PcoPersonView(record, index,
                                            self.definitions.by_id)
                seen += 1
                if limit and seen >= limit:
                    return

    # -- one person -------------------------------------------------------

    def resolve_person(self, view):
        """Find this person's attendee, or say why we could not."""
        link = identity.existing_link(self.organization, view.id)
        if link and link.attendee_id:
            return link, link.attendee

        uuid_value = mapping.ATTENDEES_UUID.read_pco(view)
        if uuid_value:
            attendee = identity.attendee_for_uuid(uuid_value)
            if attendee is not None:
                link, _ = identity.ensure_link(
                    self.organization, view.id, attendee,
                    source=PcoPersonLink.BY_UUID,
                )
                return link, attendee

        link, _ = identity.ensure_link(
            self.organization, view.id, None, state=PcoPersonLink.UNCONFIRMED
        )
        return link, None

    def report_unmatched(self, view, link):
        candidates = self.match_candidates(view)
        self.recorder.record(
            PcoDivergence.UNLINKED_PERSON, f"$.person[{view.id}]",
            note="this Planning Center person is not linked to an attendee; "
                 "pick a match or ignore it",
            severity=PcoDivergence.WARNING,
            pco_person_id=view.id, link=link,
            label=" ".join(filter(None, [
                mapping.trimmed(view.attributes.get("first_name")),
                mapping.trimmed(view.attributes.get("last_name")),
            ])) or f"person {view.id}",
            pco_value={
                "first_name": view.attributes.get("first_name"),
                "last_name": view.attributes.get("last_name"),
                "birthdate": view.attributes.get("birthdate"),
            },
            suggestion={"candidates": candidates},
        )

    def match_candidates(self, view):
        """Narrow the field before scoring, so this is not a full-table scan."""
        last = mapping.trimmed(view.attributes.get("last_name"))
        last2 = mapping.trimmed(
            mapping.FIELDS_BY_KEY["last_name2"].read_pco(view)
        )
        queryset = Attendee.objects.filter(
            division__organization=self.organization
        )
        if last or last2:
            from django.db.models import Q

            filters = Q()
            if last:
                filters |= Q(last_name__iexact=last)
            if last2:
                filters |= Q(last_name2=last2)
            queryset = queryset.filter(filters)
        queryset = queryset.select_related("division")[:200]

        pairs = [
            (attendee, mapping.canonical_birthday_from_local(
                attendee.actual_birthday, attendee.estimated_birthday))
            for attendee in queryset
        ]
        return identity.suggest_matches(view, pairs)

    def local_view(self, attendee, status_flags=None):
        flags = status_flags if status_flags is not None else statuses.flags_for(
            attendee, self.config
        )
        return mapping.LocalPersonView(attendee, flags, self.config)

    def decide_person(self, view, attendee, link):
        """Every field's fate for one person."""
        local = self.local_view(attendee)
        ignored = link.ignored_fields if link else set()
        decisions = []
        for field in mapping.PERSON_FIELDS:
            local_value = field.read_local(local)
            pco_value = field.read_pco(view)
            decision = merge.decide(field, local_value, pco_value,
                                    link.baseline if link else {}, ignored)
            decision = self._soften(field, decision)
            decisions.append((field, decision))
        return local, decisions

    def _soften(self, field, decision):
        """Turn two known non-conflicts into something quieter.

        A birthday that one side simply knows more precisely is not a
        disagreement, and a value Planning Center's schema cannot hold is a
        limitation rather than an argument. Reporting either as a conflict fills
        the report with rows nobody can act on, which is how a report stops
        being read.
        """
        if field.key != "birthday":
            return decision
        if decision.outcome == merge.CONFLICT:
            if mapping.is_refinement(decision.local_key, decision.pco_key):
                return merge.Decision(
                    key=decision.key, outcome=merge.TO_LOCAL,
                    reason="Planning Center holds the same birthday, known more precisely",
                    local=decision.local, pco=decision.pco,
                    local_key=decision.local_key, pco_key=decision.pco_key,
                    base_key=decision.base_key,
                )
            if mapping.is_refinement(decision.pco_key, decision.local_key):
                return merge.Decision(
                    key=decision.key, outcome=merge.TO_PCO,
                    reason="attendees32 holds the same birthday, known more precisely",
                    local=decision.local, pco=decision.pco,
                    local_key=decision.local_key, pco_key=decision.pco_key,
                    base_key=decision.base_key,
                )
        if decision.outcome == merge.TO_PCO \
                and not mapping.is_representable_in_pco(decision.local_key):
            return merge.Decision(
                key=decision.key, outcome=merge.SKIP,
                reason="Planning Center's birthdate cannot hold a partial date",
                local=decision.local, pco=decision.pco,
                local_key=decision.local_key, pco_key=decision.pco_key,
                base_key=decision.base_key,
            )
        return decision

    # -- applying ---------------------------------------------------------

    def apply_person(self, view, attendee, link, decisions, local):
        """Apply what is safe, record what is not, then stamp the baseline.

        A baseline entry is written only for a field that agreed, or that moved
        and whose write succeeded. Anything else keeps its old entry, which is
        what makes the same disagreement come back next run instead of quietly
        settling.
        """
        baseline = dict(link.baseline or {})
        batch = mapping.PcoWriteBatch(view.id, link.field_datum_ids)
        applied_local = False
        pending_congregation = None

        for field, decision in decisions:
            if decision.outcome == merge.AGREE:
                should, value = merge.baseline_after(decision)
                if should:
                    baseline[field.key] = value
                continue

            if decision.outcome == merge.CONFLICT:
                self.recorder.from_decision(
                    decision, field, attendee=attendee,
                    pco_person_id=view.id, link=link,
                )
                self.run.bump("conflicts")
                continue

            if decision.outcome == merge.SKIP:
                continue

            if not self.run.writes_locally and not self.run.writes_upstream:
                self.recorder.would_write(decision, field, attendee=attendee,
                                          pco_person_id=view.id, link=link)
                self.run.bump("would_write")
                continue

            if decision.writes_local:
                if not self.run.writes_locally:
                    self.recorder.would_write(decision, field, attendee=attendee,
                                              pco_person_id=view.id, link=link)
                    self.run.bump("would_write")
                    continue
                if not field.fits_locally(decision.pco):
                    self.recorder.from_decision(
                        decision, field, attendee=attendee,
                        pco_person_id=view.id, link=link,
                        kind=PcoDivergence.VALUE_TOO_LONG,
                    )
                    continue
                if field.key == "congregation":
                    pending_congregation = decision
                    continue
                if field.write_local is None:
                    continue
                # The raw value, not the comparison form. A phone number is
                # compared as bare digits so formatting cannot look like a
                # disagreement, but writing those digits back would strip the
                # formatting somebody chose.
                field.write_local(local, decision.pco)
                applied_local = True
                should, value = merge.baseline_after(decision)
                if should:
                    baseline[field.key] = value
                self.run.bump("local_writes")
                continue

            if decision.writes_pco:
                if not self.may_write_upstream:
                    self.recorder.would_write(decision, field, attendee=attendee,
                                              pco_person_id=view.id, link=link)
                    self.run.bump("would_write")
                    continue
                if field.write_pco is None:
                    continue
                field.write_pco(batch, decision.local)

        if pending_congregation is not None:
            if self.apply_congregation(local, pending_congregation, view, link,
                                       attendee):
                applied_local = True
                should, value = merge.baseline_after(pending_congregation)
                if should:
                    baseline[pending_congregation.key] = value

        for item in batch.unrepresentable:
            self.recorder.record(
                PcoDivergence.NOT_REPRESENTABLE,
                mapping.FIELDS_BY_KEY[item["key"]].pointer,
                note="Planning Center cannot store this value",
                severity=PcoDivergence.INFO, attendee=attendee,
                pco_person_id=view.id, link=link, local_value=item["value"],
            )

        if applied_local or local.pending_status:
            self.save_local(local, attendee)

        pushed = self.push_batch(batch, view, link, attendee)
        if pushed:
            for field, decision in decisions:
                if decision.writes_pco and field.key in pushed:
                    should, value = merge.baseline_after(decision)
                    if should:
                        baseline[field.key] = value

        link.baseline = baseline
        link.baseline_synced_at = self.now()
        link.field_datum_ids = batch.existing_datum_ids
        link.save()
        return link

    def apply_congregation(self, local, decision, view, link, attendee):
        """Move an attendee's Division, if the value maps to one that exists."""
        from attendees.whereabouts.models import Division

        division_id = self.config.congregation_to_division_id.get(decision.pco)
        if division_id is None:
            self.recorder.record(
                PcoDivergence.UNMAPPED_CONGREGATION, "$.person.congregation",
                note=f"no Division is mapped to the congregation "
                     f"{decision.pco_key!r}",
                attendee=attendee, pco_person_id=view.id, link=link,
                pco_value=decision.pco_key, local_value=decision.local,
            )
            return False
        division = Division.objects.filter(
            pk=division_id, organization=self.organization
        ).first()
        if division is None:
            self.recorder.record(
                PcoDivergence.UNMAPPED_CONGREGATION, "$.person.congregation",
                note=f"Division {division_id} is mapped to "
                     f"{decision.pco_key!r} but does not exist in this "
                     f"organization",
                severity=PcoDivergence.ERROR,
                attendee=attendee, pco_person_id=view.id, link=link,
                pco_value=decision.pco_key,
            )
            return False
        local.attendee.division = division
        local.dirty = True
        self.run.bump("local_writes")
        return True

    def save_local(self, local, attendee):
        """Write the attendee, then any status rows it now needs.

        Through ``.save()``, never ``update()``: the model derives
        ``infos["names"]`` from the name fields on save, reading the
        organization's OpenCC setting to do it. A bulk update would leave the
        search names describing whoever the attendee used to be.
        """
        with transaction.atomic():
            if local.dirty:
                attendee.save()
            for name, value in (local.pending_status or {}).items():
                if value is True:
                    statuses.apply_status(attendee, name, self.config,
                                          self.organization)
                    self.run.bump("status_rows")
            local.pending_status = {}
            local.dirty = False

    def push_batch(self, batch, view, link, attendee):
        """Send one person's upstream changes. Returns the slugs that landed."""
        if batch.is_empty or not self.may_write_upstream:
            return set()

        pushed = set()
        payload = batch.person_payload()
        if payload:
            try:
                self.spend_write()
                self.client.patch(f"/people/{view.id}", payload)
                pushed.update(
                    key for key, field in mapping.FIELDS_BY_KEY.items()
                    if field.slug is None
                )
            except PcoWriteIndeterminate as exc:
                self.record_indeterminate(exc, view, link, attendee)
                return set()
            except (PcoApiError, PcoNetworkError) as exc:
                self.record_write_failure(exc, view, link, attendee)
                return set()

        for slug, value in batch.custom_fields.items():
            if not self.may_write_upstream:
                break
            try:
                self.write_custom_field(view, link, slug, value)
                pushed.update(
                    key for key, field in mapping.FIELDS_BY_KEY.items()
                    if field.slug == slug
                )
            except PcoWriteIndeterminate as exc:
                # Stop touching this person. Their upstream state is now
                # unknown, and stacking further writes on top of an unknown only
                # makes the eventual reconciliation harder to reason about. The
                # rest of the queue carries on -- it is this person we back away
                # from, not the run.
                self.record_indeterminate(exc, view, link, attendee)
                return pushed
            except (PcoApiError, PcoNetworkError) as exc:
                self.record_write_failure(exc, view, link, attendee)

        for contact in batch.contacts:
            if not self.may_write_upstream:
                break
            try:
                self.spend_write()
                self.client.post(
                    f"/people/{view.id}/"
                    f"{'emails' if contact['type'] == 'Email' else 'phone_numbers'}",
                    {"data": {"type": contact["type"],
                              "attributes": {contact["attribute"]: contact["value"],
                                             "location": "Home", "primary": False}}},
                )
                pushed.add("emails" if contact["type"] == "Email" else "phones")
            except PcoWriteIndeterminate as exc:
                self.record_indeterminate(exc, view, link, attendee)
                return pushed
            except (PcoApiError, PcoNetworkError) as exc:
                self.record_write_failure(exc, view, link, attendee)

        return pushed

    def write_custom_field(self, view, link, slug, value):
        """PATCH an existing datum, or POST a new one.

        The datum id is remembered on the link so the next run patches rather
        than creating a second datum for the same definition.
        """
        datum_id = (link.field_datum_ids or {}).get(slug) \
            or view.field_datum_id(slug)
        self.spend_write()
        if datum_id:
            self.client.patch(
                f"/field_data/{datum_id}",
                {"data": {"type": "FieldDatum", "id": str(datum_id),
                          "attributes": {"value": value}}},
            )
            return datum_id

        definition_id = self.definitions.id_for(slug)
        response = self.client.post(
            f"/people/{view.id}/field_data",
            {"data": {"type": "FieldDatum",
                      "attributes": {"value": value},
                      "relationships": {"field_definition": {
                          "data": {"type": "FieldDefinition",
                                   "id": str(definition_id)}}}}},
        )
        created = ((response or {}).get("data") or {}).get("id")
        if created:
            ids = dict(link.field_datum_ids or {})
            ids[slug] = str(created)
            link.field_datum_ids = ids
        return created

    def record_indeterminate(self, exc, view, link, attendee):
        """A write that may or may not have landed. Never retried, always told."""
        self.recorder.record(
            PcoDivergence.WRITE_INDETERMINATE, f"$.person[{view.id}]",
            note=str(exc), severity=PcoDivergence.ERROR,
            attendee=attendee, pco_person_id=view.id, link=link,
        )
        self.run.bump("indeterminate_writes")

    def record_write_failure(self, exc, view, link, attendee):
        status = getattr(exc, "status", None)
        if status in (404, 422):
            # Most often a definition id that no longer exists; drop the cache
            # so the next run resolves the tab again rather than repeating it.
            fielddefs.invalidate(self.organization.id)
        self.recorder.record(
            PcoDivergence.WRITE_REFUSED, f"$.person[{view.id}]",
            note=str(exc), severity=PcoDivergence.ERROR,
            attendee=attendee, pco_person_id=view.id, link=link,
        )
        self.run.bump("failed_writes")

    # -- the whole sweep --------------------------------------------------

    def sync_people(self, limit=None, deadline=None):
        """Pull, decide and apply, one person at a time.

        Per-person error handling on purpose: one rejected record must not
        abandon the queue behind it.
        """
        processed = 0
        for view in self.iter_people(limit=limit):
            if deadline and deadline():
                break
            if self.run.cancel_requested:
                break
            try:
                self.sync_one(view)
            except SyncAborted:
                raise
            except Exception as exc:  # noqa: BLE001 - one person must not stop the run
                logger.exception("pcosync failed on person %s", view.id)
                self.recorder.record(
                    PcoDivergence.WRITE_REFUSED, f"$.person[{view.id}]",
                    note=f"the sync failed on this person: {exc}",
                    severity=PcoDivergence.ERROR, pco_person_id=view.id,
                )
                self.run.bump("errors")
            processed += 1
            self.run.bump("people_seen")
        return processed

    def sync_one(self, view):
        link, attendee = self.resolve_person(view)
        if attendee is None:
            self.report_unmatched(view, link)
            self.run.bump("unmatched")
            return link

        if self.config.pilot_attendee_ids \
                and str(attendee.id) not in self.config.pilot_attendee_ids:
            self.run.bump("skipped_not_in_pilot")
            return link

        local, decisions = self.decide_person(view, attendee, link)
        return self.apply_person(view, attendee, link, decisions, local)

    def stamp_uuids(self, limit=None):
        """Write ``attendees_uuid`` upstream and nothing else.

        Its own mode because it is the one write worth making first: it costs
        one request per person, it is idempotent, and once it is done every
        later run joins exactly instead of guessing.
        """
        stamped = 0
        for view in self.iter_people(limit=limit):
            if self.run.cancel_requested or not self.may_write_upstream:
                break
            link, attendee = self.resolve_person(view)
            if attendee is None:
                continue
            existing = mapping.ATTENDEES_UUID.read_pco(view)
            if existing == str(attendee.id):
                continue
            if existing:
                self.recorder.record(
                    PcoDivergence.FIELD_CONFLICT,
                    mapping.ATTENDEES_UUID.pointer,
                    note="this person already carries a different attendees_uuid",
                    severity=PcoDivergence.ERROR, attendee=attendee,
                    pco_person_id=view.id, link=link,
                    local_value=str(attendee.id), pco_value=existing,
                )
                continue
            try:
                self.write_custom_field(view, link,
                                        mapping.SLUG_ATTENDEES_UUID,
                                        str(attendee.id))
                link.save()
                stamped += 1
                self.run.bump("uuids_stamped")
            except PcoWriteIndeterminate as exc:
                self.record_indeterminate(exc, view, link, attendee)
            except (PcoApiError, PcoNetworkError) as exc:
                self.record_write_failure(exc, view, link, attendee)
        return stamped

    def report_unlinked_attendees(self):
        """Attendees with no Planning Center person, reported never created."""
        linked = PcoPersonLink.objects.filter(
            organization=self.organization, is_removed=False,
            attendee__isnull=False,
        ).values_list("attendee_id", flat=True)
        unlinked = Attendee.objects.filter(
            division__organization=self.organization
        ).exclude(pk__in=list(linked))[:500]
        for attendee in unlinked:
            self.recorder.record(
                PcoDivergence.UNLINKED_ATTENDEE, f"$.attendee[{attendee.id}]",
                note="this attendee has no Planning Center person",
                severity=PcoDivergence.INFO, attendee=attendee,
                label=attendee.display_label,
            )
            self.run.bump("unlinked_attendees")


def status_flags_for_many(attendee_ids, config):
    """Status flags for a batch of attendees in one query.

    One query for the sweep instead of one per person; at a thousand attendees
    that is the difference between a page load and a coffee break.
    """
    from attendees.pcosync.services.statuses import (
        attendee_content_type, flags_from_category_ids,
    )

    rows = Past.objects.filter(
        content_type=attendee_content_type(),
        object_id__in=[str(value) for value in attendee_ids],
        is_removed=False,
    ).values_list("object_id", "category_id")

    by_attendee = {}
    for object_id, category_id in rows:
        by_attendee.setdefault(str(object_id), set()).add(category_id)
    return {
        str(attendee_id): flags_from_category_ids(
            by_attendee.get(str(attendee_id), set()), config
        )
        for attendee_id in attendee_ids
    }


def run_sync(run, client=None, limit=None):
    """Entry point shared by the management command and the Celery task."""
    runner = Runner(run, client=client)
    run.state = PcoSyncRun.RUNNING
    run.started_at = run.started_at or timezone.now()
    run.save()

    try:
        run.phase = PcoSyncRun.DEFINITIONS
        runner.resolve_definitions()
        run.save()

        run.phase = PcoSyncRun.PULL_PEOPLE
        run.save()
        runner.build_uuid_index()

        if run.mode == PcoSyncRun.STAMP_UUIDS:
            runner.stamp_uuids(limit=limit)
        else:
            run.phase = PcoSyncRun.MERGE
            run.save()
            runner.sync_people(limit=limit)
            runner.report_unlinked_attendees()

        run.phase = PcoSyncRun.DONE
        run.state = PcoSyncRun.CANCELLED if run.cancel_requested \
            else PcoSyncRun.SUCCEEDED
    except SyncAborted as exc:
        run.state = PcoSyncRun.FAILED
        run.error = str(exc)
        run.add_log(str(exc), "error", timezone.now())
    except fielddefs.MissingFieldDefinitions as exc:
        run.state = PcoSyncRun.FAILED
        run.error = str(exc)
        runner.recorder.record(
            PcoDivergence.CONFIG_MISSING_FIELD, "$.config.field_definitions",
            note=str(exc), severity=PcoDivergence.ERROR,
        )
    except (PcoApiError, PcoNetworkError, PcoGoneError) as exc:
        run.state = PcoSyncRun.FAILED
        run.error = str(exc)
        run.add_log(str(exc), "error", timezone.now())
    finally:
        run.finished_at = timezone.now()
        if runner.push_blocked_reason:
            run.add_log(runner.push_blocked_reason, "warning", run.finished_at)
        run.save()
    return runner
