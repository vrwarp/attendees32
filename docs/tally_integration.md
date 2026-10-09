# Connecting Tally

[Tally](https://github.com/vrwarp/tally) is a check-in app for a church's
ministries. It can use this Attendees server as its **people backend**: the
system of record for the people on its rosters. Tally reads the roster's person
data from here, creates quick-added visitors as attendees, writes profile
edits back, files parents into families, and imports attendance history —
all over the JSON API, as a server-to-server client with a DRF token.

Attendance itself stays in Tally: under the current integration scope,
check-ins made in Tally are **not** written back here. History flows the
other way only (Attendees ➜ Tally, as a one-time import).

## Provisioning

One idempotent management command creates everything the integration needs
inside an existing organization:

```bash
python manage.py loaddata fixtures/db_seed.json   # once, if the vocabulary is not loaded
python manage.py setup_tally_integration --organization-slug <your-org-slug>
```

It creates, or finds if they already exist:

| Piece | Default | Why |
|---|---|---|
| Division | `<org>_tally` | The division created attendees are filed under. |
| Assembly | `<org>_tally_checkin` | Namespace for the meet and character. |
| Character | `<org>_tally_participant` | The role a created attendee is enrolled as. |
| Meet | `<org>_tally_gathering` | The series a created attendee is enrolled in. The auth group is put on its `infos.allowed_groups` (also when `--meet-slug` names an existing meet), because `organization_meets` only lists a meet to callers whose groups appear there. |
| Auth group | `tally_integration` | Granted to the integration user; its name is added to the organization's `groups_see_all_meets_attendees` list, which is what allows editing attendees. It is deliberately **not** added to `counselor` (see below). |
| User + attendee | `tally-integration` | The API caller. The linked attendee exists because `privileged_to_edit` walks `user.attendee.under_same_org_with(...)`. |
| DRF token | — | Printed at the end. This is the `A32_TOKEN` value in Tally. |

Every slug is overridable (`--division-slug`, `--meet-slug`, …) — point them
at existing records to reuse a division or meet you already have. The command
never moves anything between organizations; it errors instead.

The command's final output is exactly the values Tally's configuration wants
(`A32_API_BASE_URL`, `A32_TOKEN`, `A32_DIVISION_ID`, `A32_MEET_SLUG`).

## What Tally calls

All under token auth (`Authorization: Token …`), all JSON:

| Endpoint | Used for |
|---|---|
| `GET /persons/api/datagrid_data_attendee/?take&skip` | The roster sweep (the whole organization, paginated). |
| `GET /persons/api/datagrid_data_attendee/?searchValue=` | Person search. |
| `GET/POST/PATCH /persons/api/datagrid_data_attendee/[{uuid}/]` | Person read, visitor create, profile edit. |
| `GET/POST /persons/api/attendee_families/` | An attendee's families; creating one for a new parent. |
| `GET/POST /persons/api/datagrid_data_familyattendees/` | Family membership rows. |
| `GET /persons/api/all_relations/?category_id=0` | The family relation vocabulary (`child`, `parent`). |
| `GET /whereabouts/api/user_organizations/` | The organization's grade list (`infos.grade_converter`), which Tally maps its grades through. |
| `GET /occasions/api/organization_meets/?assemblies[]=<id>` | The history-import picker. |
| `GET /occasions/api/organization_team_gatherings/?meets[]=<slug>` | Gatherings of a meet, for history import. |
| `GET /occasions/api/organization_meet_character_attendances/?meets[]=<slug>` | Attendance rows, for history import. |

## What the token can and cannot see

The group is in `groups_see_all_meets_attendees` only, so the token can:

- read every attendee in the organization, with all their fields: birthdays,
  contacts, emergency contacts, and what `infos.fixed` holds, such as
  `food_pref` (allergies), `medical` and `mobility`;
- create and edit attendees, families and family memberships;
- read and write participations and attendance for the meets above.

It is **not** a counselor, so it cannot:

- read counseling or coworker notes (it sees public notes only);
- see non-family groups, drivers, or ended family memberships;
- read relations other than family ones, which is why Tally asks
  `all_relations` for `category_id=0`;
- see everyone on the directory, participation and envelope reports.

Keep anything Tally needs (such as allergies) in `infos.fixed` or a public
note, not in a counseling or coworker note. If the group was ever added to
the organization's `counselor` list by hand, the command says so; remove it
unless that access is intended.

Tests: `attendees/persons/tests/test_setup_tally_integration.py`.
