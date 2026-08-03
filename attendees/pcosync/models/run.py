from uuid import uuid4

from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel


class PcoSyncRun(TimeStampedModel):
    """One press of the Sync button.

    Not pghistory-tracked, on purpose. Every other model in this app carries a
    hand-written event model because its rows are records somebody may need to
    audit; this one is telemetry, rewritten dozens of times during a single run
    as the cursor advances. Snapshotting it would add thousands of history rows
    per run and answer no question anybody has. Please leave it untracked.

    ``cursor`` is what makes a run resumable. Progress lives in the database
    rather than in the worker's memory, so a restart mid-run picks up where it
    left off instead of starting a full-organization sweep again.
    """

    DRY_RUN = "dry_run"
    PULL_ONLY = "pull_only"
    FULL = "full"
    STAMP_UUIDS = "stamp_uuids"
    MODES = (
        (DRY_RUN, "plan only, write nothing"),
        (PULL_ONLY, "apply to attendees32, never to Planning Center"),
        (FULL, "apply in both directions"),
        (STAMP_UUIDS, "write attendees_uuid upstream and nothing else"),
    )

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STATES = (
        (QUEUED, "queued"),
        (RUNNING, "running"),
        (SUCCEEDED, "succeeded"),
        (FAILED, "failed"),
        (CANCELLED, "cancelled"),
    )
    #: States in which a run still holds the per-organization lock.
    LIVE_STATES = (QUEUED, RUNNING)

    DEFINITIONS = "definitions"
    PULL_PEOPLE = "pull_people"
    PULL_HOUSEHOLDS = "pull_households"
    MERGE = "merge"
    APPLY_LOCAL = "apply_local"
    APPLY_PCO = "apply_pco"
    HOUSEHOLDS = "households"
    DONE = "done"
    #: Order matters: the runner walks this list, and local writes land before
    #: any upstream write, so a failure in the second half leaves the first half
    #: consistent with the baseline.
    PHASES = (
        DEFINITIONS, PULL_PEOPLE, PULL_HOUSEHOLDS, MERGE,
        APPLY_LOCAL, APPLY_PCO, HOUSEHOLDS, DONE,
    )

    MAX_LOG_ENTRIES = 200

    id = models.UUIDField(
        default=uuid4, primary_key=True, editable=False, serialize=False
    )
    organization = models.ForeignKey(
        "whereabouts.Organization", default=0, null=False, blank=False,
        on_delete=models.SET(0), related_name="pco_sync_runs",
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    mode = models.CharField(max_length=12, default=DRY_RUN, choices=MODES)
    state = models.CharField(
        max_length=12, default=QUEUED, choices=STATES, db_index=True
    )
    phase = models.CharField(max_length=24, default=DEFINITIONS)
    cursor = models.JSONField(default=dict, blank=True)
    counts = models.JSONField(default=dict, blank=True)
    log = models.JSONField(default=list, blank=True)
    cancel_requested = models.BooleanField(default=False)
    chunks = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    def __str__(self):
        return f"{self.mode} sync {self.id} ({self.state})"

    @property
    def is_live(self):
        return self.state in self.LIVE_STATES

    @property
    def writes_locally(self):
        return self.mode in (self.PULL_ONLY, self.FULL)

    @property
    def writes_upstream(self):
        return self.mode in (self.FULL, self.STAMP_UUIDS)

    @property
    def percent(self):
        try:
            return int(self.PHASES.index(self.phase) / (len(self.PHASES) - 1) * 100)
        except ValueError:
            return 0

    def add_log(self, message, level="info", at=None):
        """Append to a bounded ring, so a long run cannot grow the row forever."""
        entries = list(self.log or [])
        entries.append({
            "at": at.isoformat() if at else None,
            "level": level,
            "message": message,
        })
        self.log = entries[-self.MAX_LOG_ENTRIES:]

    def bump(self, key, amount=1):
        counts = dict(self.counts or {})
        counts[key] = counts.get(key, 0) + amount
        self.counts = counts

    class Meta:
        db_table = "pcosync_runs"
        ordering = ("-created",)
        indexes = [
            models.Index(fields=["organization", "-created"],
                         name="pcosync_run_recent"),
        ]
