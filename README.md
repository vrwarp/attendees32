# Attendees

Attendees in Django 5.2
## An app for general event management
- Tracking who/when/where/what of any activities with attendance records.
- Monolith architecture on docker [![Cookiecutter Django](https://img.shields.io/badge/built%20with-Cookiecutter%20Django-ff69b4.svg?logo=cookiecutter)](https://github.com/cookiecutter/cookiecutter-django/) and Javascript([DevExtreme](https://js.devexpress.com/Licensing/#NonCommercial)) with Postgres/PostGIS & Redis

<img src="attendees/media/private-media/attendee_portrait/draft_screenshot.jpg"  alt="participations_screenshot_draft" width="100%"/>

[![Black code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black)

License: MIT

## Settings

Moved to [settings](http://cookiecutter-django.readthedocs.io/en/latest/settings.html).

## Basic Commands

### Setting Up Your Users

-   To create a **normal user account**, just go to Sign Up and fill out the form. Once you submit it, you'll see a "Verify Your E-mail Address" page. Go to your console to see a simulated email verification message. Copy the link into your browser. Now the user's email should be verified and ready to go.

-   To create an **superuser account**, use this command:

        $ python manage.py createsuperuser

For convenience, you can keep your normal user logged in on Chrome and your superuser logged in on Firefox (or similar), so that you can see how the site behaves for both kinds of users.

### Type checks

Running type checks with mypy:

    $ mypy attendees

### Test coverage

To run the tests, check your test coverage, and generate an HTML coverage report:

    $ coverage run -m pytest
    $ coverage html
    $ open htmlcov/index.html

#### Running tests with pytest

    $ pytest

### Live reloading and Sass CSS compilation

Moved to [Live reloading and SASS compilation](http://cookiecutter-django.readthedocs.io/en/latest/live-reloading-and-sass-compilation.html).

### Celery

This app comes with Celery.

To run a celery worker:

``` bash
cd attendees
celery -A config.celery_app worker -l info
```

Please note: For Celery's import magic to work, it is important *where* the celery commands are run. If you are in the same folder with *manage.py*, you should be right.

### Email Server

In development, it is often nice to be able to see emails that are being sent from your application. For that reason local SMTP server [MailHog](https://github.com/mailhog/MailHog) with a web interface is available as docker container.

Container mailhog will start automatically when you will run all docker containers.
Please check [cookiecutter-django Docker documentation](http://cookiecutter-django.readthedocs.io/en/latest/deployment-with-docker.html) for more details how to start all containers.

With MailHog running, to view messages that are sent by your application, open your browser and go to `http://localhost:8025`

## Deployment

The following details how to deploy this application.

### Docker

See detailed [cookiecutter-django Docker documentation](http://cookiecutter-django.readthedocs.io/en/latest/deployment-with-docker.html).

## User stories

<details>
  <summary>Click to expand all meeting discussions</summary>

### Epic user
- As a user, I can login and use the app
- As an administrator, I can assign/update all users to different characters, such as teacher/helper/students, etc.
- As kid program organizer, I can create/update the groups of kid programs, such as "Shining Stars", etc.
- As kid program organizer, I can create/update lessons of kid programs for different quarter/dates, such as Rock@9/1/2019
- As a user, I can see groups and lesson public info of kid programs. (please define public info, such as time/location/stuff to bring/wear, etc)

### Epic parent
- As a parent, I can register/assign/change my kids (to lesson level?)
- As a parent, I can see my kids' lesson info, including dates/time/location(/leading teacher name?)
- As a parent never join kid programs before, given the passcode send to my cell#/email, I can register my kids.
- As a parent, given the passcode send to my cell#/email, I can login with parent's one cell#, zip-code and first name in English of my kids (even if they are twins).


### Epic coworker
- As teacher/coworker, I can see class rosters, which lists teachers/helpers/students/location/time of lessons
- As a teacher/coworker, I can add/change myself to lessons
- As a teacher/coworker, I can assign/change students to lessons
- As a teacher/coworker, I can text/paging parents (future)

### Epic developer
- As a developer of the app, I need to define flexible data structures storing kid programs, including user info and characters, groups, lessons.

### 20191024 meeting notes
- As a parent I can register kids for multiple programs/events.
- As a staff/organizer, I can add/copy kids to the programs/events next year without repeatedly keyin kids' data
- As a staff/organizer, I need to see kids grade, as kids grade may not reflecting their edge, and their grade needs auto-advance every year
- As a user, I can see languages depends on my browser settings (Chinese/English/Spanish, etc) (not in V1)
- As a staff/organizer, I need to see students' siblings relationship  (non real time processing is fine)
- As a non-parent registering kids, I have to enter kid parent info.
- As a coworker I need to register withOUT kids
- As a staff/organizer, when I click each session's class title, I will be linked to google drive for course materials.
- Last, probably redesign a non row-based listing for staff/organizer's day view or student roster view (mobil phone friendly)

### 20200213 meeting notes
- As a parent I can be notified for the incoming classes, so that I can respond with RSVP or take absent for my kids.
- As a parent I can be notified to update contact info/address for my kids.
- As a coworker I can be notified for the incoming classes, so that I can respond with RSVP or take leave.
- As a organizer(coworkers?) I can be notified early when coworkers take leaves on the incoming class.
- As a organizer(coworkers?) I can assign students to different class, maybe or maybe not from student roster.
- As a coworker I can take/retract the students attendance anytime in the class or check students attendance after classes.
- As a secretary I can receive all class attendance counts summary periodically.
- As a coworker, I can check or update BOTH age and grade of a student (age and grade of the same student may vary a lot).
- As a coworker, I can see both age and grade of a student (age and grade may vary a lot) periodically advanced automatically.

#### page priority
- student rosters (with their medical concerns, parent contact, and possibly other attendances) for the incoming classes
- leader/coworker list for the incoming classes (for teacher availability and arrangement)

#### how to direct parents/coworker to use app (my own thoughts)
- Need to have some real data (secretary address database in MS Access)
- Initial registration by invite to parents/coworkers email/phone (combine with yearly contact update page)

</details>

## mockup
1. https://marvelapp.com/9dj5heb
2. https://marvelapp.com/prototype/876j52i

## data models
https://dbdiagram.io/d/5d5ff66eced98361d6dddc48

## [Deploy on Linux in production mode](https://cookiecutter-django.readthedocs.io/en/latest/deployment-with-docker.html)

<details>
  <summary>Click to expand all</summary>

* install docker and docker-compose, such as `sudo apt  install docker docker-compose`
* add web user to the docker group by `sudo usermod -aG docker <<web user name>>  && sudo service docker restart`
* Assuming git is available, git clone the repo by `git clone https://github.com/xjlin0/attendees32.git`.  Please do NOT clone under public html folder or guest will be able to see media, keys and passwords.
* create a production setting by `vi .envs/.production/.django` with 640 and save the following content. Ensure using a non-default ADMIN_URL , add your DJANGO_ALLOWED_HOSTS and ensure DJANGO_DEBUG is False.
```
# General
# ------------------------------------------------------------------------------
# DJANGO_READ_DOT_ENV_FILE=True
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_SECRET_KEY=<<your django secret key>>
DJANGO_HISTORY_CHAIN_KEY=<<your history chain key, see Audit history>>
DJANGO_ADMIN_URL=<<any cryptic string as admin path>>
DJANGO_ALLOWED_HOSTS=<<your domain name>>,127.0.0.1,localhost
DJANGO_DEBUG=False
ENV_NAME=production
# Security
# ------------------------------------------------------------------------------
# TIP: better off using DNS, however, redirect is OK too
DJANGO_SECURE_SSL_REDIRECT=False
# SSL_CERT_DIR=/etc/ssl/certs
# SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
# Email
# ------------------------------------------------------------------------------
DJANGO_SERVER_EMAIL=

MAILGUN_API_KEY=
MAILGUN_DOMAIN=


# AWS
# ------------------------------------------------------------------------------
DJANGO_AWS_ACCESS_KEY_ID=
DJANGO_AWS_SECRET_ACCESS_KEY=
DJANGO_AWS_STORAGE_BUCKET_NAME=

# django-allauth
# ------------------------------------------------------------------------------
DJANGO_ACCOUNT_ALLOW_REGISTRATION=True

# Gunicorn
# ------------------------------------------------------------------------------
WEB_CONCURRENCY=4


# Redis in docker is exposed to Host in the port REDIS_HOST_PORT from the repo root .env file
# ------------------------------------------------------------------------------
REDIS_URL=redis://redis:6379/0

# Celery
# ------------------------------------------------------------------------------

# Flower
CELERY_FLOWER_USER=<<YOUR CELERY_FLOWER_USER NAME>>
CELERY_FLOWER_PASSWORD=<<YOUR CELERY_FLOWER_PASSWORD>>
GOOGLE_MAPS_API_KEY=<<Your Google map API key>>

# Sentry
SENTRY_FRONTEND_LIB=https://js.sentry-cdn.com/<<your sentry JS frontend library>>.min.js
SENTRY_DSN="<<your backend sentry DSN>>"
SENTRY_TRACES_SAMPLE_RATE=1.0
SENTRY_ARTIFICIAL_API_DEBUG=False   # The API to artificially create an error to see if Sentry catch the log.
# visit https://<<your server domain name>>/sentry-debug/ or type `Sentry.captureException(new Error("successfully triggered frontend error"));` to see created error monitored by Sentry
```
* double check user id of your web user in production.yml:
```
user: "1001"
```
* create a production setting by `vi .envs/.production/.postgres` with 640 and save the following content. Ensure the db password changed.
```
# PostgreSQL
# ------------------------------------------------------------------------------
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=attendees
POSTGRES_USER=<<production database user name>>
POSTGRES_PASSWORD=<<production database user password>>
```
* create a [email credential](https://docs.gravityforms.com/sendgrid-api-key/) files by `vi .envs/.local/.mailgun.env` with 640 and save the following example content. (yes, local, really)
```
MAILGUN_API_KEY=YOUR_REAL_API_KEY
DJANGO_DEFAULT_FROM_EMAIL=your@email.com
MAILGUN_SENDER_DOMAIN=mailgun.YOUR_REAL.DOMAIN
EMAIL_HOST=mailgun
```
* if other staging ran previously (such as local), please remove it like `docker-compose -f local.yml down -v`. Also please remove previous private media photos at attendees32/attendees/media/private-media/attendee_portrait/*
* double check if previous [docker images needs to be removed](https://medium.com/@wlarch/no-space-left-on-device-when-using-docker-compose-why-c4a2c783c6f6). It will also remove attendees user images too.
* double check the domain name in `compose/production/traefik/traefik.yml` and `attendees/contrib/sites/migrations/0003_set_site_domain_and_name.py`
* setup env variables for django secret key in .envs/.production/.django:
```
DJANGO_ALLOWED_HOSTS=your.domain.name,another.domain.name,127.0.0.1,localhost
DJANGO_SECRET_KEY=<<production Django secret key>>
DJANGO_HISTORY_CHAIN_KEY=<<production history chain key, kept with the recovery sheet>>
DJANGO_HISTORY_ANCHOR_FILE=/data/history-anchors.txt
DJANGO_HISTORY_ANCHOR_RECIPIENTS=<<officer@example.org,clerk@example.org>>
```
* build and start the production machine by `docker-compose -f production.yml build`
* migrate database by
`docker-compose -f production.yml run django python manage.py migrate`  (do NOT makemigration on prod)
* update content types after migration by `docker-compose -f production.yml run django python manage.py update_content_types`
* create 2 superusers by `docker-compose -f production.yml run django python manage.py createsuperuser`
* import the seed data by `docker-compose -f production.yml run django python manage.py loaddata fixtures/db_seed`
* Do NOT collect static file. However, if the server previously started, you can clear the collected static file by `docker-compose -f production.yml run django python /app/manage.py collectstatic --noinput --clear --no-post-process`
* prepare all member's photos from different server.
* copy the real data to attendees/scripts/real_data/ and import real data by `docker-compose -f production.yml run django python manage.py load_access_csv attendees/scripts/real_data/tblHousehold20220929m.csv attendees/scripts/real_data/tblPeople20220929m.csv attendees/scripts/real_data/tblAddress20220929m.csv cfcch_chinese_ministry cfcch_crossing_ministry cfcch_children_ministry cfcch_congregation_data d7c8Fd_cfcch_congregation_member d7c8Fd_cfcch_congregation_directory d7c8Fd_cfcch_congregation_baptized d7c8Fd_cfcch_congregation_english_worship_roster d7c8Fd_cfcch_congregation_chinese_worship_roster d7c8Fd_cfcch_congregation_believer d7c8Fd_cfcch_junior_regular_the_rock d7c8Fd_cfcch_junior_regular_little_foot`

* start server by `docker-compose -f production.yml up -d`
* enter Django shell by `docker-compose -f production.yml run django python manage.py shell`
* go to Django admin to add the first organization and all groups to the first user (superuser) at http://<<your domain name>>:8008/<ADMIN_URL>/users/user/
* if using proxy on apache, please set `ProxyPreserveHost on` to pass host header in requests, so that the email links will have the correct domain name.
* For keeping the site surviving reboot, add starting of the Django upon system reboot, such as `sudo su user_name sh -c 'sleep 99 && cd ~user_name/repo_dir && docker-compose -f production.yml up -d' >> /tmp/attendee_startup.log` (need work)
</details>
* enter Redis-CLI by `docker exec -it redis redis-cli`

## Running on SQLite

The application runs on PostgreSQL (the default) or on SQLite with nothing but the database setting:

```
DATABASE_URL=sqlite:////data/attendees/attendees.sqlite3
```

The settings then open each connection with `transaction_mode=IMMEDIATE`, a 30 second busy timeout,
WAL journaling and foreign keys on, and close it after every request, so one writer at a time proceeds
while readers keep reading; only write requests open a transaction at all (see Phase 6 of the plan).
`migrate` builds a new database from the same migrations as PostgreSQL. Expect one write at a time: a
second writer waits up to the timeout, which suits an office of a few staff and a congregation of a
few thousand, not a public site.

What to know when operating it:

- **Keep the file on local disk**, never on NFS, SMB or another network share: SQLite's locking is
  not reliable there and a corrupted database is the usual result.
- **Back up with SQLite's online backup**, not by copying the live file (a copy taken during a write is
  inconsistent): `sqlite3 attendees.sqlite3 ".backup /backups/attendees-$(date +%F).sqlite3"`, or run
  [Litestream](https://litestream.io/) beside the application for continuous replication. Encrypt the
  copy before it leaves the machine, as for the PostgreSQL dumps.
- **Run a few workers**, for example `gunicorn config.wsgi --workers 3`; more workers do not add
  write throughput, since writes serialize on the file.
- **Encryption at rest** is the disk's job (see the security track). SQLCipher for the file itself was
  considered and deferred: build it only for a machine without disk encryption.
- Two known differences are documented rather than worked around: names with non-ASCII characters can
  sort differently (SQLite compares bytes; PostgreSQL uses a locale collation), and `icontains` on
  ordinary text columns ignores case only for ASCII letters (the search column lowercases in Python,
  so searches are unaffected).

The history's replay (`history_replay --to file.sqlite3`) writes a SQLite file too, whatever the live
database is.

## Audit history

Every change to a tracked record is an event in one table, `history_event`: which record, the whole
record as it stood, who made the change (the request, the Celery task, or the shell and its
operating-system user) and when. The writer is the application itself (`attendees.history`); nothing
depends on database triggers, so the history is the same on every database backend. Each event is
sealed onto a chain with an HMAC, which is what makes the trail tamper-evident.

Settings, in the `.django` environment file:

- `DJANGO_HISTORY_CHAIN_KEY` (required in production): the key of the chain. Generate it like a secret
  key, keep it in the environment file on the encrypted volume, and write it on the recovery sheet with
  the other secrets. Someone who copies the database without it cannot rewrite an event and recompute
  the chain behind it. Losing it does not lose data: the events still read, but the seal can no longer be
  checked.
- `DJANGO_HISTORY_ANCHOR_FILE`: where the daily anchor is appended (a file on the encrypted volume).
- `DJANGO_HISTORY_ANCHOR_RECIPIENTS`: the officers who are mailed each anchor.
- `DJANGO_HISTORY_AUDIT_RECIPIENTS`: who is mailed when a verification fails (defaults to the admins).

The daily routine, as management commands or the Celery tasks of the same names (schedule them with
django-celery-beat in the admin):

```bash
python manage.py history_anchor        # once a day: append the head of the chain to the anchor file and mail it
python manage.py verify_history        # once a night: chain, anchors and the replay against the live tables
python manage.py verify_history --incremental   # any time: only the events since the last clean run
```

An anchor is the head of the chain (`seq`, `mac`, time): a few dozen characters that reveal nothing
about the data. Once a month, copy the latest one into the board minutes. The verifier stores each run
as a `HistoryAudit` (visible in the admin under History) and, on a failure, mails the first bad event,
which also brackets when it happened: between the last anchor that still matches and the first that
does not.

Reading and using the history:

- The admin's History button on any tracked record lists its events, who made each and what changed.
- Admin > History > History events lists everything; filter by user and pick a period to see what one
  person changed.
- Restore: select one event in that list and run "Restore the record to this version". The record is
  saved back through the normal path, so the restore is itself recorded with who did it.
- `python manage.py history_replay --as-of 2026-03-01` counts the records as they stood on a day;
  `--to /tmp/that-day.sqlite3` writes them into a SQLite file the normal queries can run against
  (`Model.objects.using("history_replay")` after `attendees.history.replay.open_sqlite(path)`), with
  nothing touched in the live database. `--diff` compares the replay with the live tables, which is how
  a change made with no event (a direct `psql` edit) is found.

What the history does not hold: passwords (left out of every snapshot on purpose), sessions, content
types, Celery schedules, uploaded files (the path is recorded, the file is in the backups), and the
events themselves. Erasing a person follows the written procedure through the normal screens, so the
changes are ordinary events; earlier events keep the earlier values under the board's retention rule.

## Security: what leaves the building, and what a stolen machine opens

The design is sized to two threats: a stolen machine or backup, and a break-in through the
application. Each paragraph below says what the code does and what the operator sets up.

### Nothing readable leaves the building (S1)

- **Error reports** go to Sentry without personal data: `send_default_pii` is off, local variables
  are not collected, and a `before_send` hook strips the user, cookies, headers, query strings and
  request bodies, so a report carries the stack trace and nothing that names a member. Self-hosting
  GlitchTip on the church server is the alternative if even that is too much. The browser-side SDK
  loads only when `SENTRY_FRONTEND_LIB` is set; leave it unset, since it would have members' browsers
  fetch a script from Sentry's CDN and report to Sentry directly.
- **Browser libraries** (DevExtreme, jQuery, Bootstrap, ExcelJS, JSZip, FileSaver, signature_pad)
  are served from `static/vendor/` with their original integrity hashes, so a member's browser talks
  to the church server alone; a packet capture of a session should show no other host.
- **Geocoding** stays with Google's geocoder: about fifty new addresses a year, sent one street
  address at a time with no name attached.
- **Email**: the account emails are allauth's and carry a link and a username, nothing else; the
  gathering and attendance reports carry counts. A local SMTP relay (Postfix on the server, forwarding
  to the provider over TLS) lets the provider see envelopes rather than content; set `EMAIL_HOST` to
  it.
- **Logs** stay on the encrypted volume: container logs are bounded and rotated by Docker (five files
  of 20 MB per service), and the application's own request and access lines have the query string
  removed, so a search term or a person's key is never written to a log.
- **Second factor**: staff and superuser accounts, the roles that see other people's records, must
  enrol a second factor (an authenticator app or a passkey) on their next sign-in and cannot open any
  page until they have; `DJANGO_MFA_ENFORCED=True` extends that to every account.
- **Listening ports**: `production.yml` publishes gunicorn (8008) and Flower (5555) on the host's
  loopback only, as Redis already was, so from outside only Traefik on 443 (and SSH from the local
  network) listen. Confirm after a deploy with `ss -tlnp` on the host and a port scan from another
  machine.
- **HSTS** is a year (`DJANGO_SECURE_HSTS_SECONDS`, default 31536000); lower it only while changing
  the TLS setup.

### Encryption at rest and the recovery sheet (S2)

Three layers, each answering one way a copy of the data could be taken:

1. **The disk.** LUKS on the data volume with two keyslots: one bound through Clevis to a Tang
   service on a small second device in another locked room, so the disk opens only on the church
   network and a reboot after a power cut needs nobody present; the other a recovery passphrase on the
   recovery sheet, for the day the Tang device dies. Never the TPM alone, which would let a stolen
   machine unlock itself. A server carried out of the building stays ciphertext.
   ```bash
   # on the server, once; the Tang device serves http://tang.church.lan
   sudo clevis luks bind -d /dev/sdX2 tang '{"url":"http://tang.church.lan"}'
   sudo systemctl enable clevis-luks-askpass.path
   # the second keyslot, typed from the sheet when asked
   sudo cryptsetup luksAddKey /dev/sdX2
   ```
2. **Application secrets.** The only application-level key is the history chain key
   (`DJANGO_HISTORY_CHAIN_KEY`). It lives in the environment file on the encrypted volume, readable by
   the application user alone, and goes on the recovery sheet. There is no key service and no
   per-person key. No column is encrypted: pastoral notes are not kept in the app, so a dump reveals
   the directory and nothing written about anyone. If notes ever come in, `Note.body` gets an
   encrypted field with one service key then, and the history writer encrypts the same field inside
   its snapshots.
3. **Backups.** The `backup` maintenance script of the postgres container encrypts the database dump
   and a tarball of the file store to an `age` public key before either touches disk, copies both to a
   cloud bucket with `rclone`, and removes local copies older than the retention period. It is
   configured from the postgres environment file; the bucket's credentials go there too, as rclone's
   environment form, so nothing is mounted into the container:
   ```bash
   # .envs/.production/.postgres
   BACKUP_AGE_RECIPIENT=age1...        # the public key printed on the recovery sheet
   BACKUP_RCLONE_REMOTE=church-bucket:attendees/backups
   BACKUP_KEEP_DAYS=90
   RCLONE_CONFIG_CHURCH_BUCKET_TYPE=s3           # or b2, azureblob, ...; see rclone's documentation
   RCLONE_CONFIG_CHURCH_BUCKET_PROVIDER=Other
   RCLONE_CONFIG_CHURCH_BUCKET_ENDPOINT=https://...
   RCLONE_CONFIG_CHURCH_BUCKET_ACCESS_KEY_ID=...
   RCLONE_CONFIG_CHURCH_BUCKET_SECRET_ACCESS_KEY=...
   ```
   Run it nightly from the host's crontab, since the container has no scheduler of its own:
   ```
   0 2 * * * cd /srv/attendees && docker compose -f production.yml exec -T postgres backup
   ```
   Without `BACKUP_AGE_RECIPIENT` the script still writes the plaintext dump it always did and warns;
   without `BACKUP_RCLONE_REMOTE` the backup stays on the machine and warns. Give the bucket
   versioning or an object lock and the credentials write-only rights (no delete), so a compromised
   server cannot destroy its own backup history. The private key exists only on the recovery sheet.
   Keep 90 days in the bucket; test a restore every quarter, on a machine that is not the server:
   ```bash
   rclone copy church-bucket:attendees/backups/backup_2026_03_01T02_00_00.sql.gz.age .
   age -d -i recovery-sheet-key.txt backup_2026_03_01T02_00_00.sql.gz.age > backup_2026_03_01T02_00_00.sql.gz
   docker compose -f local.yml exec postgres restore backup_2026_03_01T02_00_00.sql.gz   # or: gunzip | psql
   ```
   On SQLite the dump step is `sqlite3 attendees.sqlite3 ".backup /backups/attendees.sqlite3"` (the
   online backup, never a copy of the live file) followed by the same `age` and `rclone` steps.

**The recovery sheet** is one sheet of paper holding the `age` identity that opens the backups, the
LUKS recovery passphrase and the history chain key, each as text beside a QR code, with the `age`
public key printed alongside so `age-keygen -y` can confirm the sheet is intact. Print it offline on a
church-owned laser printer, never through a website or an office copier that keeps print jobs. Before
filing it, decrypt a real backup from the printed copy once, because printers substitute quotes and
ligatures. Two copies: one in the church safe, one with an officer at home. Write down who holds them.
Once a year, restore a backup on a laptop from the paper alone. A sheet alone opens nothing without a
backup to apply it to, and the bucket has its own credentials. A lost sheet and a dead Tang device
together mean lost data by design.

### Who saw what: the access log (S3)

Every detail page, export and print of personal data writes an `AccessLog` row: when, who, which
record, through which endpoint, from which address, and how (a detail page, an export, a print). The
person page and the single-person API log the person viewed; the directory report, the directory
preview, the participation report and the envelopes log the job and its filters. Lists and datagrids
are not logged. The rows are written after the response, in a transaction of their own, so a failed
log line never turns a page into an error.

The log is itself sensitive, since it shows who looked at whom. The model has only a view permission,
`access.view_accesslog`: give it, in Admin > Groups, to the data owner's group alone (its members need
`is_staff` to open the admin at all; superusers see it anyway), and agree with the board who reviews
the log and why before switching the review on. Nobody adds, changes or deletes rows by hand: the admin
page is read-only. Admin > Access log answers both questions: filter by model and key for who viewed a
person, by user and date for what one person did, by "print" or "export" for who took the directory. A
member viewing their own household is logged like anyone else and filtered out in the review when it
does not matter. `python manage.py prune_access_log` deletes rows older than twelve months; schedule the
Celery task of the same name nightly in Admin > Periodic tasks.

### Erasure on request and data export (S4)

No member has asked for either in the life of the system and no law requires it here, so this is a
procedure, ready if the first request comes. It was walked through once on a copy of the golden
database, and that walk-through is kept as a test (`attendees/tests/e2e/test_erasure_procedure.py`),
so the steps below are known to leave what they promise to leave.

**Export: what is held about a person.** Open, and print or save, in this order:

1. Admin > Persons > Attendees: the record (names, birthday, gender, division, photo, the `infos`
   contacts and preferences), and its History button for every past version.
2. The person page (`/persons/attendee/<id>`): household memberships and roles, addresses (Places),
   statuses and notes (Pasts), scheduling and emergency-contact links, participations (Attendings and
   AttendingMeets), registrations and attendances.
3. Admin > Users: the login, its groups, email addresses and second factors.
4. Admin > Access log filtered by the person: who looked at their record.
5. Admin > History > History events filtered by `persons.attendee` and the key: every change ever
   recorded, with who made it.

**Erasure.** Through the normal screens, so every step is an ordinary history event and the chain is
untouched; earlier events keep the earlier values under the board's retention rule, which the
requester is told. "Delete" on a screen marks a row removed and keeps it, which is what lets a slip
be undone, so the procedure ends with one shell step that removes those rows for good.

1. Confirm the request in writing and check the exceptions below.
2. On the person page: delete the notes and statuses the page shows (a note addressed to one reader
   shows only to them; the shell step below removes whatever the screens could not), the person's own
   addresses, and the household memberships. A household of their own (a one-member folk) goes with
   the membership; a shared household stays, so if its name carries the person's (a guardianship named
   after its ward, say), rename it on the household page before removing them.
3. On the same page, edit the record: first and last names to "Erased" and "member", the other names
   blank, birthday, gender and date of death cleared, the `infos` contacts emptied (the names kept
   there follow the record's name on save), and the scheduler and emergency-contact pickers emptied;
   save.
4. Keep the attendance, participation and registration rows: they now point at "Erased member" and
   keep the counts and statistics right.
5. Admin > Users: delete the login (or deactivate it if it must stay for the history's sake).
6. The shell step, for the portrait file, the links in both directions (the person as somebody
   else's scheduler or contact), and the rows the screens only marked as removed:
   ```bash
   docker compose -f production.yml run --rm django python manage.py shell
   ```
   ```python
   from django.db.models import Q
   from attendees.persons.models import Attendee, FolkAttendee, Note, Past
   from attendees.persons.models.attendee_links import AttendeeEmergencyContact, AttendeeScheduler
   from attendees.whereabouts.models import Place

   def delete_place(place):
       address = place.address
       place.delete(soft=False)
       if address and not Place.all_objects.filter(address=address).exists():
           address.delete()

   attendee = Attendee.objects.get(pk="<the record's key>")
   attendee.photo.delete(save=True)
   AttendeeScheduler.objects.filter(Q(attendee=attendee) | Q(scheduler=attendee)).delete()
   AttendeeEmergencyContact.objects.filter(Q(attendee=attendee) | Q(contact=attendee)).delete()
   for place in Place.all_objects.filter(attendee=attendee):
       delete_place(place)
   for membership in FolkAttendee.all_objects.filter(attendee=attendee).select_related("folk"):
       folk = membership.folk  # a household of their own, removed on the page: its name and address go too
       if folk.is_removed and not FolkAttendee.all_objects.filter(folk=folk).exclude(attendee=attendee).exists():
           for place in Place.all_objects.filter(folk=folk):
               delete_place(place)
           folk.delete(soft=False)
   FolkAttendee.all_objects.filter(attendee=attendee).delete()    # all_objects deletes for good;
   Note.all_objects.filter(object_id=str(attendee.pk)).delete()    # objects would only mark removed
   Past.all_objects.filter(object_id=str(attendee.pk)).delete()
   ```
   Every delete here is recorded as a `before_delete` event, like a delete on a screen.
7. Record the date in the board's register. Backups within the 90-day retention still hold the person
   and age out on their own; the history keeps the earlier values until the board's retention period
   ends.

**Exceptions** the church keeps regardless of a request: membership vote records and the counts they
rest on, financial records, and anything under a legal hold. List them on the board's register.

## DB SQL Backup & Restore process (with production.yml)
<details>
  <summary>Click to expand all</summary>

* backup current db to container `docker-compose -f production.yml exec postgres backup`
* list backup files in container `docker-compose -f production.yml exec postgres backups`
* When postgres container is up, copy all backup files from container to dev local computer `docker cp $(docker-compose -f production.yml ps -q postgres):/backups ./backups`
* When postgres container is up, copy all backup files from dev local computer to container `docker cp ./backups $(docker-compose -f production.yml ps -q postgres):/`
* When postgres container is up, restore a backup from a backup file in container `docker-compose -f production.yml exec postgres restore backup_2018_03_13T09_05_07.sql.gz`
* When postgres container is up, remove all backups from docker `docker-compose -f production.yml exec postgres sh -c "rm /backups/*"`
* print INSERT commands for a table `docker-compose -f production.yml exec postgres pg_dump --column-inserts --data-only --table=<<table name>> -d attendees --username=<<POSTGRES_USER in .envs/.production/.postgres>>`
* Enter postgres db console by `docker-compose -f production.yml exec postgres psql -d attendees --username=<<POSTGRES_USER in .envs/.production/.postgres>>`
* Clear out mfa to save an user lost phones `DELETE FROM mfa_authenticator WHERE user_id=<<user` id>>;`
</details>

## Apache Proxy configuration
Since the Django server is running on port 8008, you can use Apache to proxy the requests to the Django server. Here is an example configuration for Apache:
```
<VirtualHost *:443>
RemoteIPHeader X-Forwarded-For
RemoteIPInternalProxy 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 127.0.0.1 ::1

<LocationMatch "(?i)/(wp-(json|admin|login|includes|content)|xmlrpc|docker|\.git)">
    Require all denied
</LocationMatch>

<LocationMatch "(?i)\.(jsp|old|yaml|yml|conf|bak|backup|php|env|ini|sql|django|postgres|esp|aws)$">
    Require all denied
</LocationMatch>

<Directory /home/username/domains/your.domain.name/public_html>
    Options -Indexes +IncludesNOEXEC +SymLinksIfOwnerMatch
    Require all granted
    AllowOverride All Options=ExecCGI,Includes,IncludesNOEXEC,Indexes,MultiViews,SymLinksIfOwnerMatch
</Directory>
<Directory /home/username/domains/your.domain.name/cgi-bin>
    Require all granted
    AllowOverride All Options=ExecCGI,Includes,IncludesNOEXEC,Indexes,MultiViews,SymLinksIfOwnerMatch
</Directory>
<Proxy *>
    <RequireAll>
        Require all granted
        # IP you wanna block, multiple lines is ok
        Require not ip 163.7.5.166
    </RequireAll>
</Proxy>

RemoveHandler .php
RemoveHandler .php8.2

RewriteEngine on
RewriteCond %{HTTP_HOST} !^subdomain\.domain\.name(:[0-9]+)?$ [NC]
RewriteRule ^ - [F,L]

ProxyPreserveHost On
RequestHeader set X-Forwarded-Proto "https"
ProxyPass /.well-known !

RewriteCond %{HTTP:UPGRADE} ^WebSocket$ [NC]
RewriteCond %{HTTP:CONNECTION} Upgrade [NC]
RewriteRule ^/?(.*) "ws://127.0.0.1:8008/$1" [P]

ProxyPass / http://127.0.0.1:8008/
ProxyPassReverse / http://127.0.0.1:8008/

</VirtualHost>
```
Don't forget to enable module *header* since the webauthn needs the header.

## [How to start dev env on Linux](https://cookiecutter-django.readthedocs.io/en/latest/developing-locally-docker.html)

<details>
  <summary>Click to expand all</summary>

* double check if the dev port 8008 is open on server firewall
* add server's public ip to ALLOWED_HOSTS in settings
* install docker and docker-compose, such as `sudo apt  install docker docker-compose`
* add web user to the docker group by `sudo usermod -aG docker <<web user name>>  && sudo service docker restart`
* Assuming git is available, git clone the repo by `git clone https://github.com/xjlin0/attendees32.git`
* create a fake [email credential](https://docs.gravityforms.com/sendgrid-api-key/) files by `vi .envs/.production/.mailgun.env` and save the following fake content.
```
MAILGUN_API_KEY=YOUR_REAL_API_KEY
DJANGO_DEFAULT_FROM_EMAIL=your@email.com
MAILGUN_SENDER_DOMAIN=mailgun.YOUR_REAL.DOMAIN
EMAIL_HOST=mailgun
```
* build and start the local machine by `docker-compose -f local.yml build && docker-compose -f local.yml up -d`
* collect static file: `docker-compose -f local.yml run django python /app/manage.py collectstatic`
* Ensure the MailHog is not publicly available such as https://your.domain.name:8025
* Ensure the db password in .envs/.local/.postgres changed
* If you have Redis in local, please ensure REDIS_HOST_PORT in repo root .envs not overlapped with your local Redis port.
* Ensure using a non-default ADMIN_URL
* update content types after migration by `docker-compose -f local.yml run django python manage.py update_content_types`
* create 2 superusers by `docker-compose -f local.yml run django python manage.py createsuperuser`
* import the seed data by `docker-compose -f local.yml run django python manage.py loaddata fixtures/db_seed`, which was generated by:
  ```
docker compose -f local.yml run --rm django python manage.py dumpdata --natural-foreign --natural-primary -e users.user -e admin.logentry -e sessions.session -e contenttypes.contenttype -e sites.site -e account.emailaddress -e account.emailconfirmation -e socialaccount.socialtoken -e auth.permission -e history.historyevent -e history.historycontext -e history.historyhead -e history.historyaudit --indent 2 > fixtures/db_seed.json
  ```
* go to Django admin to add the first organization and all groups to the first user (superuser) at http://<<your domain name>>:8008/admin/users/user/
* to see django log: `docker-compose -f local.yml logs django`
</details>

## [How to start dev env on Windows](https://cookiecutter-django.readthedocs.io/en/latest/developing-locally-docker.html)
<details>
  <summary>Click to expand all</summary>

All libraries are included to facilitate offline development, it will take port 8008, 8025, 5555 when running, please change port in local.yml if those ports are occupied.
* Install [git](https://git-scm.com/downloads) and [docker for windows](https://docs.docker.com/install), which includes docker-compose.
* clone the repo by `git clone git@github.com:xjlin0/attendees30.git` and cd the repo directory `attendees30`
* create a fake [mail credential](https://docs.gravityforms.com/sendgrid-api-key/) files by `start notepad .envs/.local/.sendgrid.env` and save the following fake content. or `.envs/.local/.mailgun.env` for mailgun
```
MAILGUN_API_KEY=YOUR_REAL_API_KEY
DJANGO_DEFAULT_FROM_EMAIL=your@email.com
MAILGUN_SENDER_DOMAIN=mailgun.YOUR_REAL.DOMAIN
EMAIL_HOST=mailgun
```
* build and start the local machine by `docker-compose -f local.yml build && docker-compose -f local.yml up -d`
* upadte content types after migration by `docker-compose -f local.yml run django python manage.py update_content_types`
* create 2 superusers by `docker-compose -f local.yml run --rm django python manage.py createsuperuser`
* import the seed data by `docker-compose -f local.yml run django python manage.py loaddata fixtures/db_seed`, which was generated by:
  ```
docker compose -f local.yml run --rm django python manage.py dumpdata --natural-foreign --natural-primary -e users.user -e admin.logentry -e sessions.session -e contenttypes.contenttype -e sites.site -e account.emailaddress -e account.emailconfirmation -e socialaccount.socialtoken -e auth.permission -e history.historyevent -e history.historycontext -e history.historyhead -e history.historyaudit --indent 2 > fixtures/db_seed.json
  ```
* go to Django admin to add the first organization and all groups to the first user (superuser) at http://localhost:8008/admin123/users/user/
```
localhost or 127.0.0.1 is default ip, if your docker use a different IP and browser shows "DisallowedHost"
Please add your IP to ALLOWED_HOSTS in config/settings/local.py
```
* use browser to open http://localhost:8008/ and http://localhost:8025/
* Enter postgres db console by `docker-compose -f local.yml exec postgres psql -d attendees --username=<<POSTGRES_USER in .envs/.local/.postgres>>`
* Enter Django console by `docker-compose -f local.yml run django python manage.py shell_plus`
* remote debug in PyCharm for docker, please check [django cookie doc](https://github.com/pydanny/cookiecutter-django/blob/master/{{cookiecutter.project_slug}}/docs/pycharm/configuration.rst).
</details>
* enter Redis-CLI by `docker exec -it redis redis-cli`

## How to start dev env on macOS with VirtualBox and docker-machine
<details>
  <summary>Click to show deprecated steps to start dev env on macOS with VirtualBox and docker-machine</summary>

All libraries are included to facilitate offline development, it will take port 8008, 8025, 5555 when running, please change port in local.yml if those ports are occupied.
* clone the repo, for example, `git clone https://github.com/xjlin0/attendees.git`
* check local python version, Django coockie cutter is developed with Python 3
* There is no need to have local Django or Postgres running, but on OSX please install [Virtualbox 6](https://www.virtualbox.org/wiki/Download_Old_Builds_6_0). This repo use deprecated VirtualBox 6.0.24.  Using anything later will need to change /etc/vbox/networks.conf and Host Network Manager configurations.
* Instead of the latest OSX docker desktop, the repo is using deprecated `docker-machine`. Please [install docker/docker-machine](https://www.datamachines.io/blog/how-to-install-a-docker-machine-on-a-macos) by `brew install docker-machine docker docker-compose`.
* start the local docker machine by `brew services restart docker-machine`
* start a docker machine named "dev" by `docker-machine create --driver virtualbox dev`
* Start the dev virtual machine, your "dev" vm can be run at headless mode. Be sure to check permissions of virtual machine in the system preference.
* get all env variables from "dev" by `eval $(docker-machine env dev)`
* create a fake email credential files by `vi .envs/.local/.mailgun.env` and save the following fake content.
```
MAILGUN_API_KEY=<<any string>>
DJANGO_DEFAULT_FROM_EMAIL=fake@email.com
MAILGUN_SENDER_DOMAIN=mailgun.fake.domain
EMAIL_HOST=mailhog
```
* build and start the local machine by `docker compose -f local.yml build && docker compose -f local.yml up -d`.  If there's error about `docker-credential-desktop`,  change credsStore to credStore in `~/.docker/config.json`
* create migration files by `docker compose -f local.yml run --rm django python manage.py makemigrations`
* migrate db by `docker compose -f local.yml run --rm django python manage.py migrate`
* upadte content types after migration by `docker compose -f local.yml run django python manage.py update_content_types`
* create 2 superusers by `docker compose -f local.yml run --rm django python manage.py createsuperuser`
* import the seed data by `docker compose -f local.yml run django python manage.py loaddata fixtures/db_seed`, data were created by:
  ```
docker compose -f local.yml run --rm django python manage.py dumpdata --natural-foreign --natural-primary -e users.user -e admin.logentry -e sessions.session -e contenttypes.contenttype -e sites.site -e account.emailaddress -e account.emailconfirmation -e socialaccount.socialtoken -e auth.permission -e history.historyevent -e history.historycontext -e history.historyhead -e history.historyaudit --indent 2 > fixtures/db_seed.json
  ```
* go to Django admin to add the first organization and all groups to the first user (superuser) at http://localhost:8008/admin123/users/user/
* use browser to open http://localhost:8008/ and http://localhost:8025/
* Enter postgres db console by `docker compose -f local.yml exec postgres psql -d attendees --username=<<POSTGRES_USER in .envs/.local/.postgres>>`
* Enter Django console by `docker compose -f local.yml run django python manage.py shell_plus`
* remote debug in PyCharm for docker, please check [django cookie doc](https://github.com/pydanny/cookiecutter-django/blob/master/{{cookiecutter.project_slug}}/docs/pycharm/configuration.rst).

</details>

## How to start dev env with docker desktop on macOS (Apple chip compatible)
All libraries are included to facilitate offline development, it will take port 8008, 8025, 5555 when running, please change port in local.yml if those ports are occupied. It's Debian based.

* clone the repo, for example, `git clone https://github.com/xjlin0/attendees32.git`
* check local python version, Django cookie cutter is developed with Python 3
* Install pre-commit for python, such as `pip3 install pre-commit` (pre-commit settings are at .git/hooks/pre-commit).
* There is no need to have local docker machine, Django or Postgres running.
* Add .envs/.local/.mailgun.env
```commandline
MAILGUN_SENDER_DOMAIN=<<any fake domain name>>
DJANGO_DEFAULT_FROM_EMAIL=<<your email>>
MAILGUN_API_KEY=<<anystring or your mailgun api key with mailgun EMAIL_HOST>>
EMAIL_HOST=mailhog
```
* Install and start [docker desktop](https://www.docker.com/products/docker-desktop) (including docker compose), and [add local repo directory to file sharing in docker desktop preference](https://docs.docker.com/desktop/settings/mac/#file-sharing).
* In Docker Desktop Settings, please ensure both "Use Virtualization framework" and "Use Rosetta for x86_64/amd64 emulation on Apple Silicon" options in enabled.
* build the Debian based local machine by `docker compose -f local.yml build`
* migrate db by `docker compose -f local.yml run --rm django python manage.py migrate`
* upadte content types after migration by `docker compose -f local.yml run django python manage.py update_content_types`
* create 2 superusers by `docker compose -f local.yml run --rm django python manage.py createsuperuser`
* import the seed data by `docker compose -f local.yml run django python manage.py loaddata fixtures/db_seed`, data were created by:
* If you have Redis in local, please ensure REDIS_HOST_PORT in repo root .envs not overlapped with your local Redis port.
* optionally load the golden test congregation — 350 people, families, statuses, participations and eight weeks of attendance — by `docker compose -f local.yml run django python manage.py load_golden_data --seed`, see [docs/golden_test_data.md](docs/golden_test_data.md)
* run the browser end-to-end suite (Chromium and WebKit, TypeScript/Playwright) by `npm ci && npx playwright install --with-deps chromium webkit && npm run test:e2e:chromium` (or `:webkit`) against a running stack loaded with the golden congregation; `npm run test:e2e:ci-seed` runs the specs written against `fixtures/ci_seed.json`
* start the Debian based local machine by `docker compose -f local.yml up -d`, your site will be at http://localhost:8008/
* to see django log: `docker compose -f local.yml logs django`
* enter the Bash shell of running container `docker compose -f local.yml run django bash`
* enter Redis-CLI by `docker exec -it redis redis-cli`
* Run test by `docker compose -f local.yml run django pytest` for all tests or `docker compose -f local.yml run django pytest attendees/users/tests/test_admin.py` for running single test class, or `docker compose -f local.yml run django pytest attendees/users/tests/test_admin.py::TestUserAdmin::test_view_user` for a single test method.
* Shut down server and remove orphans `docker compose -f local.yml down --remove-orphans`


## DB SQL Backup & Restore process (with local.yml)
* backup current db to container `docker compose -f local.yml exec postgres backup`
* list backup files in container `docker compose -f local.yml exec postgres backups`
* When postgres container is up, copy all backup files from container to dev local computer `docker cp $(docker compose -f local.yml ps -q postgres):/backups ./backups`
* When postgres container is up, copy a backup file from dev local computer to container `docker cp ./backups/<filename> $(docker compose -f local.yml ps -q postgres):/backups/`
* restore a backup from a backup file in container `docker compose -f local.yml exec postgres restore backup_2018_03_13T09_05_07.sql.gz`
* print INSERT commands for a table `docker compose -f local.yml exec postgres pg_dump --column-inserts --data-only --table=<<table name>> -d attendees --username=<<POSTGRES_USER in .envs/.local/.postgres>>` 

## Find nearest neighbors
### Define google map API key in the .django env:
```
GOOGLE_MAPS_API_KEY=<your google api key>
```
### Geocoding all address:
```
docker-compose -f production.yml run django python manage.py populate_coordinates
```

## How to run test
### Django unit test:
```
timeout 300 docker compose -f local.yml run django pytest
```
### Playwright (with chromium) e2e test when Django server is up:
```
C_PASSWORD=your_password_for_superuser_in_seed timeout 300 npx playwright test --workers=1
```
Please also define the repository secret `C_PASSWORD` in Github for running e2e in CI/CD

The `ci-seed` specs sign in as `jack`, the seed's superuser, and a superuser must have a second
factor. Enrol him with an authenticator app once and pass its secret to the specs:
```
export C_TOTP_SECRET=$(python -c 'import base64, secrets; print(base64.b32encode(secrets.token_bytes(20)).decode())')
python manage.py shell -c "import os; from allauth.mfa.totp.internal.auth import TOTP; from attendees.users.models import User; TOTP.activate(User.objects.get(username='jack'), os.environ['C_TOTP_SECRET'])"
C_PASSWORD=... C_TOTP_SECRET=$C_TOTP_SECRET npx playwright test --project=ci-seed --workers=1
```
The CI jobs do the same with a secret made for the run. The golden suite (`--project=chromium`)
needs nothing extra: `load_golden_data` enrols the golden superuser and writes the secret into the
manifest.

## Todo & progress:

<details>
  <summary>Click to expand all</summary>

- [x] make auth group not organization specific, and counselling note check on organization
- [x] [PR#30](https://github.com/xjlin0/attendees30/pull/30) Past can replace Note on DB level, Attendee.progressions and calls/requests, so that any name lists such as status can be easily queried. (membership remains as AttendingMeet with category for active/inactive)
  - [x] make Past model generic
  - [ ] any past status list (Past level)
  - [ ] Attendance roster to Past auto conversion (AttendingMeet <=> Past has been implemented)
- [x] attendee detail page
  - [x] server side process of Attendees list & search page
  - [x] AttendingMeet form of Attendee update page
  - [x] [PR#3](https://github.com/xjlin0/attendees30/pull/3) FamilyAttendee datagrid of Attendee update page
  - [x] [PR#1](https://github.com/xjlin0/attendees30/pull/1) Move Address to Contact
  - [x] [PR#2](https://github.com/xjlin0/attendees30/pull/2) Personal & family Address of Attendee update page
  - [x] [PR#4](https://github.com/xjlin0/attendees30/pull/4) Dynamic contacts of Attendee update page
  - [x] [PR#9](https://github.com/xjlin0/attendees30/pull/9) Permission controlled blocks in single attendee update page, i.e. different blocks/user-settings for different groups
  - [x] [PR#11](https://github.com/xjlin0/attendees30/pull/11) Generic models such as Note, Place, Past need to have organization column instead of infos
  - [x] [PR#12](https://github.com/xjlin0/attendees30/pull/12) Add Past as Note
  - [x] [PR#13](https://github.com/xjlin0/attendees30/pull/13) [PR#14](https://github.com/xjlin0/attendees30/pull/14) [PR#15](https://github.com/xjlin0/attendees30/pull/15) Create new instance of Attendee & attending update page with params with meet
  - [x] [PR#16](https://github.com/xjlin0/attendees30/pull/16) delete function for human error
  - [x] [PR#5](https://github.com/xjlin0/attendees30/pull/5) Modify Attendee save method to combine/convert names by OpenCC to support searches in different text encoding, and retire db level full_name.
  - [x] [PR#8](https://github.com/xjlin0/attendees30/pull/8) implement secret/private relation/past general
  - [x] some relationship may be internal and only shows to cowokers/admin, in category/boolean/infos column?
  - [x] [PR#32](https://github.com/xjlin0/attendees30/pull/32) Folk model support secret but attendee UI folkattendee doesn't support it
  - [x] Passed away attendees also need to be removed from emergency contact/scheduler of others.
  - [ ] Calendar view
    - [x] [2PR#26](https://github.com/xjlin0/attendees32/pull/26) show the Event/Occurrence calendar of Meet/Gathering
    - [ ] Rejecting gathering with conflicts on location/time, upon user selected the location dropdown.
    - [ ] Editing UI for single Meet (with multiple Events) config with scheduling rules & locations.
  - [ ] Rich format of note for Past on UI? [Using DevExtreme's html editor instead of summernote?](https://blog.devgenius.io/best-free-wysiwyg-editor-python-django-admin-panel-integration-d9cb30da1dba) Django summer note cannot make migration on prod:
```
adam@panel:~/attendees32$ docker-compose -f production.yml run django python manage.py makemigrations
Creating network "attendees32_default" with the default driver
Creating volume "attendees32_production_postgres_data" with default driver
Creating volume "attendees32_production_postgres_data_backups" with default driver
Waiting for PostgreSQL to become available...
PostgreSQL is available
Migrations for 'django_summernote':
  /usr/local/lib/python3.9/site-packages/django_summernote/migrations/0003_alter_attachment_id.py
    - Alter field id on attachment
Traceback (most recent call last):
  File "/app/manage.py", line 31, in <module>
    execute_from_command_line(sys.argv)
  File "/usr/local/lib/python3.9/site-packages/django/core/management/__init__.py", line 419, in execute_from_command_line
    utility.execute()
  File "/usr/local/lib/python3.9/site-packages/django/core/management/__init__.py", line 413, in execute
    self.fetch_command(subcommand).run_from_argv(self.argv)
  File "/usr/local/lib/python3.9/site-packages/django/core/management/base.py", line 354, in run_from_argv
    self.execute(*args, **cmd_options)
  File "/usr/local/lib/python3.9/site-packages/django/core/management/base.py", line 398, in execute
    output = self.handle(*args, **options)
  File "/usr/local/lib/python3.9/site-packages/django/core/management/base.py", line 89, in wrapped
    res = handle_func(*args, **kwargs)
  File "/usr/local/lib/python3.9/site-packages/django/core/management/commands/makemigrations.py", line 190, in handle
    self.write_migration_files(changes)
  File "/usr/local/lib/python3.9/site-packages/django/core/management/commands/makemigrations.py", line 228, in write_migration_files
    with open(writer.path, "w", encoding='utf-8') as fh:
PermissionError: [Errno 13] Permission denied: '/usr/local/lib/python3.9/site-packages/django_summernote/migrations/0003_alter_attachment_id.py'
```
- [x] Move attendee/attendees page out of data assembly -- some coworkers need to see all attendees of the organization, with a way to see only family members for general users
  - [x] [PR#17](https://github.com/xjlin0/attendees30/pull/17) remove all previous attendee edit testing pages
  - [x] [PR#18](https://github.com/xjlin0/attendees30/pull/18) remove attendee list page dependency of path params and take search params from user for assembly slug
  - [x] [PR#19](https://github.com/xjlin0/attendees30/pull/19) rename and move attendees/attendee page, and show attendees based on auth groups
  - [x] [PR#26](https://github.com/xjlin0/attendees30/pull/26) make special Past as Meet to be shown in Attendees, also creating such Past will result in AttendingMeet creation
- [x] Gathering list (server side processing with auto-generation)
  - [x] [PR#20](https://github.com/xjlin0/attendees30/pull/20) gatherings datagrid filtered by meets and date ranges
  - [x] [PR#21](https://github.com/xjlin0/attendees30/pull/21) django-schedule with Meet
  - [x] [PR#22](https://github.com/xjlin0/attendees30/pull/22) can gathering generation automatic?
  - [x] [PR#23](https://github.com/xjlin0/attendees30/pull/23) sorting & grouping by server side processing
- [x] data [db backup/restore](https://cookiecutter-django.readthedocs.io/en/latest/docker-postgres-backups.html) to survive new releases and migrations
- [x] Add Attendee+ buttons in above pages should deduplicate before creation by providing existing names for users to choose
  - [x] [PR#24](https://github.com/xjlin0/attendees30/pull/24) fix self attendee page error
  - [x] [PR#28](https://github.com/xjlin0/attendees30/pull/28) from Attendee detail and attendee list page
  - [x] [PR#30](https://github.com/xjlin0/attendees30/pull/30) importer load_access_csv need to import bap date and believer, not only by membership.
- [x] Move "age, grade and mobility" from Attending.infos to Attendee.infos.fixed, since same attendee may join many activities
- [x] [2PR#19](https://github.com/xjlin0/attendees32/pull/19) AttendingMeet list (server side processing)
  - [x] [2PR#18](https://github.com/xjlin0/attendees32/pull/18) new AttendingMeet datagrid filtered by meets and date ranges
  -  ~~auto-generation of AttendingMeet by django-schedule with certain Past~~
- [x] Attendance list (server side processing with auto-generation)
  - [x] [2PR#20](https://github.com/xjlin0/attendees32/pull/20) new attendance datagrid filtered by meets and date ranges, since current datagrid_assembly_all_attendances & datagrid_coworker_organization_attendances cannot show correct attendings with real data (returning attendings only limit to 20 and not matching to filtered attendance's attending -- refresh the datagrid & reloading attending lookup with attendance filters)
  - [x] [2PR#23](https://github.com/xjlin0/attendees32/pull/23) auto-generation attendance by attending meet and recent attendance status
  - [x] Easier UI for batch add attendingmeet
  - [x] member list (attendance level with editing category, with sort by family/last names)
- [ ] Folkattendee List grouped by Folk
  - [ ] For carpooling, needs consent too, as well as shown in Attendee update page.
- [x] [2PR#22](https://github.com/xjlin0/attendees32/pull/22) Create roster page (no real-time update for multiple coworkers in v1)
  - [ ] Coworker roster on phone/web, X: characters, Y: dates(gatherings)
- [ ] Division specific menu links, such as including selected meets in the search params
  - [ ] Junior
  - [ ] Data
- [x] [2PR#14](https://github.com/xjlin0/attendees32/pull/14) Audit log/history/vision of data
  - [x] find library and install: maybe django-pghistory with AggregateEvent
  - [x] each model level version
  - [ ] document aggregation level version
  - [x]  [2PR#25](https://github.com/xjlin0/attendees32/pull/25) upgrade to django-pghistory v2.4+ for various bug fixes.
- [x] [New repo] upgrade to Django 3.2LTS for support of DEFAULT_AUTO_FIELD
   -[x] accept partial date on all attending/past, etc django-date-extensions or django_partial_date. Also use Javascript solution to make yearless date back to 1800, so birthday of "1999 August" will be 08-01-1999 and "May 24th" will be 05-24-1800
   -[x] 3.1: use Django JSONField instead of Postgres JSONField
   -[x] With Django Cookie-cutter, decide async or not (uvicorn high CPU usage in Mac only, but web_socket can be only with use_async)
- [x] deploy to AWS EC2
   - [x] [PR#25](https://github.com/xjlin0/attendees30/pull/25) ensure libraries loaded other than MacOS
- [ ] Export pdf
  - [x] [2PR#21](https://github.com/xjlin0/attendees32/pull/21) directory booklet
  - [ ] mail labels (avery template) or printing envelops
- [ ] Since Relationship replaced by FolkAttendee, probably create titles in DB/Redis for relationships among families such as siblings, etc
- [ ] i18n Translation on model data, django-parler maybe?
- [x db currently allow non-uniq email, but duplicated email will cause send mail failure.
- [x] retire django summer note
- [x] restart production docker lost all images, perhaps because docker was not installed correctly with rootless mode, thus the user become first available non-root user 1001. (resolved by add user option in production yaml)
- [x] modify django-allauth so that the host in the email activation link won't be http://localhost:8008/ even in production. Perhaps Header, RequestHeader. Solution: use [ProxyPreserveHost On](https://stackoverflow.com/a/25225871/4257237) and [Require expr %{HTTP_HOST} == "example.com"](https://stackoverflow.com/a/43323088/4257237)
- [x] Setup [Django allauth with social login](https://learndjango.com/tutorials/django-allauth-tutorial), [steps](https://instamentor.com/articles/django-all-auth-tutorial-with-google-and-django-cookiecutter).
</details>

## Issues:

<details>
  <summary>Click to expand all</summary>

- [ ] for ordinary users:
   -[ ] even as scheduler seeing other's attendee detail view, the joined meet doesn't show group name (i.e. Hagar cannot see Ishmael in "the Rock")
   -[ ] If manager A checked "secret shared with you" for a model with "share secret with you" and uniq constrain such as Relationship, manager B can't see it (expected) and creating another relationship will fail due to uniq constrain (not expected). If relating uniq constraint, after manager B create the very same relationship, manager A will see duplicated relationship.
</details>

## Design decisions:

<details>
  <summary>Click to expand all</summary>

- [ ] for all users:
   -[x] the viewers of a secret relationship/past are attendees instead of users, since a secret relationship exists regardless of user accounts. For example, kid X bullied kid Y, and counsellors can configure kids parents & teachers to see it regardless of parent/teachers user accounts existence or switches.
   -[ ] There is no decision on display notes/infos of Relationships/FamilyAttendee/Past. Ordinary end users can see their families, so role-dependent showing/hiding notes columns need designs, such as storing allowed columns in Menu.infos read by User.allowed_url_names()?  Currently UI only expose separated sections on Past which conditionally show to ordinary end users.
   - [ ] let different meets/assemblies share the very same attending via attendingmeet and registration, since AttendingMeetService.flip_attendingmeet_by_existing_attending cannot know attendings from attendee update, and creating attending is by default when creating new attendee.  If force registration/attendingmeet validation, creating attendingmeet will be hard on UI.  Different attendings of the same attendee will be considered for summer meeting where registration with price involve. 
</details>
