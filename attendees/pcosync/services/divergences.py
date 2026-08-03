"""Recording what the two systems disagree about.

A diagnostic, and only a diagnostic -- the phrasing is pcomirror's and the
discipline is worth copying exactly. Nothing in this module repairs anything.
Resolution happens later, by a person, and works by moving a baseline rather
than by queueing a write.

The one subtlety is that an unresolved disagreement must stay *one row*,
refreshed each run. A weekly sync that opened a fresh row per week for the same
unanswered question would make the report unusable precisely when somebody
finally sat down to work through it.
"""

from django.utils import timezone

from attendees.pcosync.models import PcoDivergence


class DivergenceRecorder:
    """Collects divergences for one run and writes them idempotently."""

    def __init__(self, organization, run=None, now=None):
        self.organization = organization
        self.run = run
        self.now = now or timezone.now
        #: dedupe keys touched this run, so a caller can close what went away.
        self.seen = set()
        self.counts = {}

    def record(self, kind, pointer, *, note="", severity=PcoDivergence.WARNING,
               attendee=None, pco_person_id=None, link=None, label="",
               local_value=None, pco_value=None, baseline_value=None,
               suggestion=None, infos=None):
        attendee_id = getattr(attendee, "id", None)
        key = PcoDivergence.build_dedupe_key(pointer, pco_person_id, attendee_id)
        self.seen.add(key)
        self.counts[kind] = self.counts.get(kind, 0) + 1
        now = self.now()

        existing = PcoDivergence.objects.filter(
            organization=self.organization, dedupe_key=key,
            resolution=PcoDivergence.OPEN, is_removed=False,
        ).first()

        if existing:
            # Refresh the values -- a conflict whose two sides have both moved
            # again is still the same open question, but the numbers on it
            # should be current.
            existing.run = self.run
            existing.link = link or existing.link
            existing.attendee = attendee or existing.attendee
            existing.kind = kind
            existing.label = label or existing.label
            existing.local_value = local_value
            existing.pco_value = pco_value
            existing.baseline_value = baseline_value
            existing.note = note or existing.note
            existing.severity = severity
            if suggestion is not None:
                existing.suggestion = suggestion
            existing.last_seen_at = now
            existing.save()
            return existing

        return PcoDivergence.objects.create(
            organization=self.organization, run=self.run, link=link,
            attendee=attendee, pco_person_id=pco_person_id or "",
            kind=kind, pointer=pointer, dedupe_key=key, label=label,
            local_value=local_value, pco_value=pco_value,
            baseline_value=baseline_value, suggestion=suggestion or {},
            note=note, severity=severity,
            first_seen_at=now, last_seen_at=now,
        )

    def from_decision(self, decision, field, *, attendee=None, pco_person_id=None,
                      link=None, kind=PcoDivergence.FIELD_CONFLICT,
                      severity=PcoDivergence.WARNING):
        return self.record(
            kind, field.pointer, note=decision.reason, severity=severity,
            attendee=attendee, pco_person_id=pco_person_id, link=link,
            label=field.label,
            local_value=_jsonable(decision.local),
            pco_value=_jsonable(decision.pco),
            baseline_value=_jsonable(decision.base_key),
        )

    def would_write(self, decision, field, *, attendee=None, pco_person_id=None,
                    link=None):
        """A dry run's output: what a real run would have done.

        Recorded as a divergence rather than only counted, because the plan is
        the deliverable on day one and somebody has to be able to read it.
        """
        direction = ("attendees32" if decision.writes_local else "Planning Center")
        return self.record(
            PcoDivergence.WOULD_WRITE, field.pointer,
            note=f"would write to {direction}: {decision.reason}",
            severity=PcoDivergence.INFO,
            attendee=attendee, pco_person_id=pco_person_id, link=link,
            label=field.label,
            local_value=_jsonable(decision.local),
            pco_value=_jsonable(decision.pco),
            baseline_value=_jsonable(decision.base_key),
        )

    def close_absent(self, kinds=None):
        """Mark open rows this run did not see again as resolved elsewhere.

        Somebody editing one side into agreement is the ordinary way a
        disagreement ends, and it should not need a click to disappear. Scoped
        to ``kinds`` so a caller only closes what it actually re-examined.
        """
        queryset = PcoDivergence.objects.filter(
            organization=self.organization, resolution=PcoDivergence.OPEN,
            is_removed=False,
        ).exclude(dedupe_key__in=self.seen)
        if kinds:
            queryset = queryset.filter(kind__in=kinds)
        return queryset.update(
            resolution=PcoDivergence.RESOLVED_ELSEWHERE,
            resolved_at=self.now(),
        )


def _jsonable(value):
    """JSONField needs plain types; a sentinel or a date is neither."""
    from attendees.pcosync.merge import MISSING

    if value is MISSING:
        return None
    if isinstance(value, (str, int, float, bool, list, dict)) or value is None:
        return value
    return str(value)
