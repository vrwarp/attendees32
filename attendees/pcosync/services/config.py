"""Per-organization sync settings, read from ``Organization.infos``.

Everything lives in one JSON blob under
``Organization.infos["settings"]["pcomirror"]``, editable through the
django-json-widget admin the project already uses for org settings. That was a
deliberate choice: one surface to edit, and per-organization values, since each
organization syncs to its own Planning Center org through its own mirror.

**The API key is in there too, and that has a cost worth knowing.**
``Organization`` is pghistory-tracked and its event model snapshots the whole
``infos`` column, so a key written here is copied into
``whereabouts_organizationshistory`` on every subsequent edit to any org
setting, and into every database backup. Rotating the key does not scrub the
old one. pghistory cannot exclude a sub-key of a JSON column, so this is not
something a bit more care in this module could avoid. What this module *can*
do, and does, is refuse to hand the key to anything that renders: see
``redacted()``, which is what the page and every serializer must use.

Every default means "does nothing". A freshly-configured organization is
disabled, in dry-run, with the push kill switch off and a create budget of
zero, so the failure mode of a half-finished setup is an inert button rather
than a surprise write into a live church database.
"""

from dataclasses import dataclass, field
from typing import Optional

SETTINGS_KEY = "pcomirror"

#: Slugs the sync cannot work without. A missing one aborts the run before any
#: write, rather than silently syncing a subset and looking like it worked.
REQUIRED_SLUGS = (
    "attendees_uuid",
    "chinese_first_name",
    "chinese_last_name",
    "baptized",
    "believer",
    "congregation",
)

DEFAULTS = {
    "enabled": False,
    "dry_run": True,
    "push_enabled": False,
    "base_url": "",
    "api_key": "",
    "field_definition_tab_id": "",
    "max_creates_per_run": 0,
    "max_writes_per_run": 50,
    "max_mirror_staleness_minutes": 60,
    "pilot_attendee_ids": [],
    "congregation_to_division_id": {},
    "household_role_to_relation_id": {
        "parent_guardian": 30,
        "child": 27,
        "adult": 25,
        "other_adult": 25,
    },
    "status_category_ids": {"baptized": 5, "believer": 4, "disbeliever": 22},
}


@dataclass
class PcoSyncConfig:
    """A resolved view of one organization's settings."""

    organization_id: Optional[int] = None
    enabled: bool = False
    dry_run: bool = True
    push_enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    field_definition_tab_id: str = ""
    max_creates_per_run: int = 0
    max_writes_per_run: int = 50
    max_mirror_staleness_minutes: int = 60
    pilot_attendee_ids: list = field(default_factory=list)
    congregation_to_division_id: dict = field(default_factory=dict)
    household_role_to_relation_id: dict = field(default_factory=dict)
    status_category_ids: dict = field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    @property
    def division_id_to_congregation(self) -> dict:
        """The inverse map, derived rather than stored so it cannot drift."""
        return {
            int(division_id): value
            for value, division_id in self.congregation_to_division_id.items()
            if division_id is not None
        }

    @property
    def relation_id_to_household_role(self) -> dict:
        """First role wins where several map to one Relation.

        ``adult`` and ``other_adult`` both land on *unspecified*, so the inverse
        is genuinely lossy. Sorting makes which one wins stable rather than
        dependent on dict ordering, so repeated syncs do not flap between them.
        """
        inverse = {}
        for role in sorted(self.household_role_to_relation_id):
            relation_id = self.household_role_to_relation_id[role]
            inverse.setdefault(int(relation_id), role)
        return inverse

    def blocking_reason(self) -> Optional[str]:
        """Why this organization cannot sync, in words a person can act on."""
        if not self.enabled:
            return "Planning Center sync is switched off for this organization"
        if not self.base_url:
            return "no pcomirror base_url is configured"
        if not self.api_key:
            return "no pcomirror api_key is configured"
        if not self.field_definition_tab_id:
            return "no field_definition_tab_id is configured"
        return None

    def redacted(self) -> dict:
        """The settings, safe to render.

        Anything that reaches a template, a serializer or a log line goes
        through here. The key is reported as present or absent -- which is the
        only thing an operator needs to know -- and never echoed back.
        """
        data = {
            key: getattr(self, key)
            for key in DEFAULTS
            if key not in ("api_key",)
        }
        data["api_key_set"] = bool(self.api_key)
        return data


def config_for(organization) -> PcoSyncConfig:
    """Read one organization's settings, falling back to the inert defaults."""
    infos = getattr(organization, "infos", None) or {}
    raw = (infos.get("settings") or {}).get(SETTINGS_KEY) or {}
    merged = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}

    return PcoSyncConfig(
        organization_id=getattr(organization, "id", None),
        enabled=bool(merged["enabled"]),
        # An explicit false is the only thing that turns dry-run off. A typo, a
        # missing key or a null all leave it on.
        dry_run=merged["dry_run"] is not False,
        push_enabled=merged["push_enabled"] is True,
        # A blank base_url means "not overridden", never "cleared" -- so saving
        # an unrelated setting cannot silently repoint a deployed sync at a
        # different organization's data.
        base_url=(merged["base_url"] or "").strip(),
        api_key=(merged["api_key"] or "").strip(),
        field_definition_tab_id=str(merged["field_definition_tab_id"] or "").strip(),
        max_creates_per_run=_non_negative_int(merged["max_creates_per_run"], 0),
        max_writes_per_run=_non_negative_int(merged["max_writes_per_run"], 50),
        max_mirror_staleness_minutes=_non_negative_int(
            merged["max_mirror_staleness_minutes"], 60
        ),
        pilot_attendee_ids=[str(v) for v in (merged["pilot_attendee_ids"] or [])],
        congregation_to_division_id=dict(merged["congregation_to_division_id"] or {}),
        household_role_to_relation_id=dict(
            merged["household_role_to_relation_id"] or {}
        ),
        status_category_ids=dict(merged["status_category_ids"] or {}),
    )


def write_config(organization, changes, save=True):
    """Merge ``changes`` into the organization's settings blob.

    Reads and rewrites only the ``pcomirror`` sub-key, so an admin editing
    something else at the same time does not lose it -- and so this function
    cannot accidentally reset the rest of ``settings``.
    """
    infos = dict(organization.infos or {})
    settings = dict(infos.get("settings") or {})
    current = dict(settings.get(SETTINGS_KEY) or {})
    current.update({k: v for k, v in changes.items() if k in DEFAULTS})
    settings[SETTINGS_KEY] = current
    infos["settings"] = settings
    organization.infos = infos
    if save:
        organization.save()
    return config_for(organization)


def _non_negative_int(value, fallback):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(0, number)
