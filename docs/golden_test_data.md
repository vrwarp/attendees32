# Golden test data: a 350-member Chinese church

`fixtures/db_seed.json` gives the application its *vocabulary* — organizations,
divisions, categories, relations, assemblies, meets, characters, teams, menus
and auth groups — plus nineteen demo people to illustrate it. The golden
dataset keeps the vocabulary, replaces the nineteen, and puts a whole
congregation inside it, so that a count is a count and a report has something
to print.

```
python manage.py load_golden_data --seed
```

```python
def test_something(golden):                 # pytest fixture, see below
    grace = golden.attendee("chen_grace")
```

## The congregation

| bucket | count | division |
| --- | --- | --- |
| Chinese immigrant adults | 200 | 中文部 (`cfcch_chinese_ministry`) |
| English-congregation adults | 100 | The Crossing (`cfcch_crossing_ministry`) |
| Youth, grades 6–12 | 25 | The Crossing |
| Children, nursery–grade 5 | 25 | Junior Ministry (`cfcch_children_ministry`) |
| **total on the roster** | **350** | |
| a household that moved away | 3 | soft-deleted, outside the 350 |

Ten of the Chinese-congregation adults also sit in the English service and hold
a participation in both.

151 family folks, plus carpool and "other relationship" folks that cut across
them. Every family has a street address in the East Bay; a few people also
carry a personal address (a college dorm, a mailing address).

## Where the shape came from

The distributions are modelled on the Planning Center People payloads captured
in the pcomirror divergence reports:

| in the PCO export | in the golden data |
| --- | --- |
| `child` true for ~1/3 of rows | 50 of 350 are youth or children |
| `status` inactive for ~14% | ~14% of participations are category *Inactive* |
| `membership`: Full Member / Regular Attendee / Visitor / null | Pasts of category *member* / *receive* / *visitor* / none |
| `grade` from −1 (pre-K) to 12 | `infos.fixed.school_grade`, mapped into the organization's `grade_converter` |
| `birthdate` 1885-01-01 as "unknown" | `estimated_birthday` of `1800`, this codebase's placeholder |
| `name` that is not first + last | `first_name`/`last_name` romanised plus `last_name2`/`first_name2` in Han characters, with `infos.names` derived |
| the same person found under two spellings | 陳 appears as both *Chen* and *Chan*; 黃 as *Huang* and *Wong* |
| `medical_notes`, `nickname` | `infos.fixed.medical`, `infos.fixed.nick_name` |

Names repeat on purpose — several people are called Ruian, two children share
the given name 明恩. Tests that need to identify one person use their id, and
the search tests rely on the collisions.

## Sixteen households written by hand

A generator will not produce the shapes a church actually has to cope with, so
these are written out one by one. Each is reachable by key, e.g.
`golden.folk("HH_CHEN_THREE_GEN")`.

| key | what it exercises |
| --- | --- |
| `HH_CHEN_THREE_GEN` | three generations; the grandmother died four years ago and keeps a `deathday` and a finished folk membership |
| `HH_LIU_SINGLE_MOTHER` / `HH_LIU_EX_HUSBAND` | a divorce: children with the mother, the father in his own household, an *ex spouse* folk spanning both |
| `HH_WONG_BLENDED` | remarriage: a son, a step-daughter, a shared baby, and a half-sibling folk |
| `HH_XU_GUARDIAN` | a parachute student — a *ward*, not a son; his guardians are his emergency contacts and schedulers |
| `HH_WANG_WIDOW` | a widow living alone, birth year unknown, mobility 3, driven to church by a deacon |
| `HH_MIXED_MARRIAGE` | husband in 中文部, wife in The Crossing, child in Junior Ministry |
| `HH_GUO_FOUR_GEN` | four generations down the female line, eldest 94 with a year-and-month birthday |
| `HH_ZHANG_PASTOR` | the pastor's family; one adult child on the worship team, one away at college with a *paused* participation |
| `HH_NEW_IMMIGRANT` | arrived five months ago, all visitors, not in the printed directory |
| `HH_GRAD_ROOMMATES` | three graduate students, each their own family of one, sharing a non-family folk |
| `HH_FOSTER_CARE` | a caregiver/care-receiver placement; the birth mother attends separately and is inactive |
| `HH_TSAI_RESTAURANT` | restaurant workers: no email at all, a weekday fellowship, children in the after-school club |
| `HH_LEE_ABC` | second-generation family, English congregation throughout |
| `HH_DEPARTED` | soft-deleted household that must never surface in a live query |
| `HH_CARPOOL_EAST` | a carpool folk with one driver and three riders from three different households |

## What is tracked on each person

Names (romanised, Han, and the derived `infos.names` in both scripts, because
`opencc_convert` is on for this organization) · gender · actual, year-only,
year-and-month and unknown birthdays · death dates · grade and insurer for
minors · food preferences, medical notes, mobility, nicknames · one or two
phone numbers and email addresses, or none at all · emergency contacts and
schedulers, by attendee id · baptism, believer, member, visitor, catechumen,
interested, disbeliever, coworker and deacon statuses as `Past` rows ·
education history · public, coworker and counseling notes, the confidential
ones addressed to one reader through `infos.show_secret`.

Participations cover Sunday worship in both languages, the choir by section,
adult Sunday school, all twelve Chinese fellowships, the children's programme
by grade, the after-school club, the library, and the English youth ministry —
in every AttendingMeet category the vocabulary has (scheduled, active, primary,
secondary, remote, leave, paused, inactive, confirmed).

The 2025 summer retreat has four prices, household registrations with
donations, credits and paper/online applications, panel groups, drivers and
passengers, and a few people who pulled out.

Eight weeks of Sunday history for four meets: about 2 900 attendance rows,
marked present, absent, remote or on leave, with gaps — nobody attends every
single week.

## Signals are left switched on

Half the point of the dataset is that it exercises them, so the builder creates
one side of each pair and lets the application produce the other:

* saving an `Attendee` files them into a hidden non-family folk and opens an
  `Attending`;
* saving a baptism `Past` opens the participation on 已受洗
  (`Organization.infos.settings.past_category_to_attendingmeet_meet`);
* saving a participation on 已信主 writes the matching `Past` back
  (`Meet.infos.automatic_creation.Past`);
* saving a participation on 通訊錄 flips `Folk.infos.print_directory`
  (`Meet.infos.automatic_modification.Folk`).

## Vocabulary the golden builder adds

The seed has no English youth ministry, so the builder adds an assembly
(`cfcch_crossing_youth`), its characters, two meets and three teams; characters
and a practice meet for the existing Crossing worship team; and student/teacher
characters for the Chinese Sunday school. Their primary keys start at 100, above
the seed's range.

## Logins

Eleven personas, all with the password `golden-password-1`:

| username | groups | attendee |
| --- | --- | --- |
| `golden_superuser` | *(none)* | — |
| `golden_data_organizer` | data_organizer, organization_participant | Pastor Zhang |
| `golden_counselor` | data_counselor, organization_participant | 徐建國 |
| `golden_children_organizer` | children_organizer, organization_participant | Jonathan Lee |
| `golden_children_coworker` | children_coworker, organization_participant | Joanna Lee |
| `golden_conference_organizer` | conference_organizer, organization_participant | 馬麗雲 |
| `golden_member` | organization_participant | 陳志明 |
| `golden_crossing_member` | organization_participant | Wilson Wong |
| `golden_youth` | organization_participant | Grace Chen, 15 |
| `golden_unaffiliated` | unspecified_group | — |
| `golden_outsider` | organization_participant | — (no organization) |

`golden_superuser` has no auth groups on purpose: `RouteGuard` reads groups, not
`is_superuser`, so a superuser is refused at every page — worth pinning.

Each persona also gets a verified `allauth` `EmailAddress`, because
`ACCOUNT_EMAIL_VERIFICATION` is mandatory and the browser specs sign in through
the real form.

## Running it

The dataset is deterministic. Every UUID primary key comes from `uuid5` of a
fixed namespace and a stable key, so two runs produce identical identifiers.
Dates are relative to *today*, so ages and "currently participating" windows
stay true however long the code sits.

```
python manage.py load_golden_data --seed                       # build it
python manage.py load_golden_data --seed --dump fixtures/golden.json
```

`--dump` writes a `loaddata`-able fixture, which is how to hand the same
congregation to another service. The fixture is not committed: it is several
megabytes of derived data and the builder is the source of truth.

## The e2e suite

`attendees/tests/e2e/` drives the whole application against this congregation:

| module | covers |
| --- | --- |
| `test_golden_dataset.py` | the census itself, and the four signals |
| `test_pages.py` | every page × every persona, against the seed's permission matrix |
| `test_persons_api.py` | every `/persons/api/…` endpoint, read and write |
| `test_occasions_api.py` | meets, characters, teams, gatherings, attendances, statistics, calendars |
| `test_whereabouts_api.py` | organizations, divisions, sites and addresses |
| `test_reports.py` | the printed directory, participation lists, envelopes |
| `test_permissions.py` | SpyGuard, privileged pages, confidential notes |
| `test_tally_integration.py` | the token-authenticated server-to-server sweep |
| `browser/test_browser_navigation.py` | sign-in, the group-driven menu, the guards and the printed pages, in a real browser |
| `browser/test_browser_datagrids.py` | the DevExtreme grids: do they boot, ask the right endpoint and render the answer |

### The browser layer

Everything above talks HTTP. That proves the routing, the guards, the
serializers and the queries — but every roster screen in this application is an
empty `<div>` server-side that DevExtreme fills over AJAX, so none of it proves
a screen works. `attendees/tests/e2e/browser/` opens the pages in **Chromium and
WebKit** and waits for the grids to have rows in them.

Playwright is driven directly rather than through `pytest-playwright`, so both
engines run on a bare `pytest` with no extra flags: the `browser` fixture is
parametrised and every spec runs twice.

Three things about the harness are worth knowing:

* **It runs its own server.** pytest-django's `live_server` fixture drags in
  `transactional_db`, which truncates every table after each test — and the
  golden congregation, committed once for the whole session, is exactly what
  gets truncated. The `app_server` fixture starts a plain `LiveServerThread`
  instead. The consequence is that anything the *server* writes is committed
  for real, so these specs stay read-only.
* **Third-party assets are fetched once.** The pages pull DevExtreme (4 MB),
  jQuery plugins and Bootstrap from public CDNs. The `cdn` fixture fetches each
  URL once per session and replays it from memory, passing the bytes through
  unchanged so the templates' subresource-integrity hashes still check out.
* **The login rate limit is reset between tests.** `ACCOUNT_RATE_LIMITS`
  allows three failed logins per IP per ten minutes, and allauth answers a
  rate-limited attempt with the same message as a wrong password — so one test
  of a bad password would otherwise break every login after it.

Browsers are installed in `compose/local/django/Dockerfile`
(`playwright install --with-deps chromium webkit`). Locally:

```
playwright install --with-deps chromium webkit
```

Without them the browser specs skip, **unless** `ATTENDEES_REQUIRE_BROWSERS=1`
is set, which turns a missing engine into a failure. CI sets it, so a broken
image cannot quietly stop running them.

The congregation is built once per session and committed, because rebuilding it
costs about a minute. `pytest_collection_modifyitems` in `attendees/conftest.py`
therefore runs the e2e suite **last** — committed data is visible to every other
test in the session, and the unit tests create fixtures with hard-coded primary
keys that would collide — and the session fixture flushes on the way out so a
reused database is left as it was found.

```
pytest attendees/tests/e2e            # the suite alone
pytest attendees/tests/e2e/browser    # Chromium and WebKit only
pytest                                # everything; e2e still runs last
```
