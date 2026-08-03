# Planning Center sync, through pcomirror

## Objective

Give attendees32 a staff-triggered, two-way sync with a Planning Center People
organization: names (Latin and CJK), birthday, gender, contacts, the custom-field
tab, and household structure.

The governing rule is **never auto-resolve**. When both systems hold different
values for the same field and both have moved since they last agreed, neither is
written; the disagreement is recorded for a person to settle. Everything else
follows from needing to tell "who changed this" from "these differ".

## Key files & context

`pcomirror` serves Planning Center's own JSON:API, so there is no mirror protocol
to implement — `attendees/pcosync/client.py` is a plain PCO client with its base
URL pointed elsewhere. Reading through the mirror does buy three things the real
API cannot give, and each is used: `410 Gone` forwarding to a merged survivor, a
`504` that honestly says a write may or may not have landed, and the mirror's own
statement of how stale it is (which is what lets a push refuse a stale read).

| Module | Holds |
|---|---|
| `merge.py` | The three-way decision. Imports no Django; test it in a bare interpreter. |
| `mapping.py` | The field table, both directions, and the type coercions. Pure. |
| `client.py` | HTTP, pagination, retry rules, error taxonomy, redaction. |
| `services/runner.py` | One run, phase by phase, with every budget. |
| `services/households.py` | Families: the exact-set join and the never-remove rule. |
| `services/config.py` | `Organization.infos["settings"]["pcomirror"]`. |
| `models/` | `PcoPersonLink` (the join and the baseline), `PcoHouseholdLink`, `PcoDivergence`, `PcoSyncRun`. |

Existing project machinery this leans on, rather than reimplementing:
`Utility.update_or_create_last`, `AttendeeService.create_or_update_first_folk`,
and the `Past` → `AttendingMeet` signal in `persons/signals.py`.

## Things worth knowing before changing any of it

**The baseline is the whole design.** `PcoPersonLink.baseline` holds each field's
value as of the last agreement. It is stamped **only** on agreement, or on a
write that succeeded. Stamping it on a conflict makes the next run see "neither
side changed" and quietly settle a disagreement nobody answered.

**A sync never clears.** A value going from something to nothing is not
propagated, in either direction, and the same rule covers household membership.
Real data gets deleted by people, in one system at a time, on purpose.

**baptized and believer are rows, not columns.** They are `Past` rows whose
`Category` is mapped to a `Meet` by
`Organization.infos["settings"]["past_category_to_attendingmeet_meet"]` — in the
seed, category 5 (*baptized*) → meet 16, category 4 (*receive*) → meet 17. The
sync writes the `Past` and lets the existing signal make the `AttendingMeet`,
exactly as when a coworker adds one by hand. It deliberately does **not** use the
signal's `"importer"` escape hatch, which would also suppress the `Attending` the
mapping depends on.

**Two unknown-year sentinels.** attendees32 uses 1800, Planning Center uses 1885.
`mapping.py` translates both to a canonical `----MM-DD`; neither ever reaches the
baseline and neither system sees the other's.

**Compare normalised, write raw.** `(626) 555-0134` and `+16265550134` must not
read as a disagreement, and neither side's formatting may be rewritten by the
other.

**Identity comes from `/field_data`, never from filtering `/people`.** On
`/people` each `where[...]` key compiles to its own independent `EXISTS`, so
asking for a person with a datum of one definition *and* a datum of one value
matches anybody holding both somewhere — not in the same datum.

**People are walked ordered by `created_at`.** Pagination is offset-only, so
ordering on a column that changes mid-walk lets rows shuffle between pages and be
skipped silently.

**`POST` is never retried.** No idempotency key exists, and a lost response is
indistinguishable from a request that never left.

**A new page is a bare 403 without a `Menu` row.** `RouteGuard` authorizes from
the `Menu`/`MenuAuthGroup` tables and the nav renders from the same tree;
migration `0002_seed_menu` creates both.

## Configuration

All of it lives in `Organization.infos["settings"]["pcomirror"]`, editable in the
django-json-widget admin. Every default means *does nothing*: disabled, dry-run,
push off, zero creates.

The API key is in there too, by decision. The cost is real and is documented in
`services/config.py`: `Organization` is pghistory-tracked and its event model
snapshots the whole `infos` column, so a rotated key persists in
`whereabouts_organizationshistory` and in backups. pghistory cannot exclude a
sub-key of a JSON column. What the code does do is refuse to render it —
everything that reaches a template, serializer or log goes through
`PcoSyncConfig.redacted()`.

## Rollout

Seven layers, in the order to remove them:

1. `enabled: false` — the button is dead.
2. `dry_run: true` — plans everything, writes nothing, records each intended
   change as a `would_write` divergence. This is the deliverable of day one.
3. `push_enabled: false` — apply to attendees32 only.
4. `max_creates_per_run: 0` — may update, may not create.
5. `max_writes_per_run: 50` — bounds a bad mapping to fifty rows.
6. `pilot_attendee_ids` — three volunteers, by name, first.
7. Point `base_url` at a pcomirror holding a **read-only** key (`read:*`, no
   `write`) for the first week. A defence in a system attendees32 does not
   control beats a flag in one it does.

Plus `mode="stamp_uuids"`, which writes the `attendees_uuid` custom field and
nothing else. Run it first: it is one request per person, idempotent, and once
done every later run joins exactly instead of guessing.

Expect a first real run to open a lot of conflicts. With no baseline there is no
evidence about who moved what, so every field where the two differ is genuinely
ambiguous. That is the policy working, not the sync misbehaving — which is
exactly why dry-run exists, so the number is known before anything moves.

## Verification

```bash
docker compose -f local.yml build                     # picks up requests
docker compose -f local.yml run --rm django python manage.py migrate
docker compose -f local.yml run django pytest attendees/pcosync/

# against a local pcomirror, with a key that cannot write
pcomirror create-api-key --name attendees32 --scopes 'read:*'
docker compose -f local.yml run django python manage.py pcosync --org=<slug> --dry-run
```

Then open `/pcosync/sync/` as a data admin. The page is gated by `RouteGuard`, so
if it 403s, check the `Menu` rows before anything else.

## Rollback

The sync writes through `.save()` under
`pghistory.context(modifier="pcomirror sync", run=<id>)`, so everything one run
touched is greppable in the `*history` tables and revertable from them. Reverting
the app itself is `migrate pcosync zero`; the seed migration removes its own
`Menu` rows.
