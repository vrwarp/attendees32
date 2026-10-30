from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from attendees.history import replay


class Command(BaseCommand):
    help = (
        "Rebuild the tracked tables from the history. Without options, counts the records as of now; "
        "--as-of picks the moment; --to writes them into a SQLite file the normal queries can run against "
        "(Model.objects.using('history_replay')); --diff compares the replay to now with the live tables."
    )

    def add_arguments(self, parser):
        parser.add_argument("--as-of", help="A date or datetime (ISO 8601); the tables as they stood then")
        parser.add_argument("--to", help="Path of a new SQLite file to write the rebuilt tables into")
        parser.add_argument("--diff", action="store_true", help="Compare the replay to now with the live tables")

    def handle(self, *args, **options):
        as_of = None
        if options["as_of"]:
            as_of = parse_datetime(options["as_of"]) or parse_date(options["as_of"])
            if as_of is None:
                raise CommandError(f"cannot read {options['as_of']!r} as a date or datetime")
            if not hasattr(as_of, "hour"):
                as_of = timezone.make_aware(timezone.datetime.combine(as_of, timezone.datetime.max.time()))
            elif timezone.is_naive(as_of):
                as_of = timezone.make_aware(as_of)
        if options["diff"]:
            report = replay.compare()
            if not report:
                self.stdout.write("the replay matches the live tables")
                return
            for model, found in report.items():
                self.stdout.write(
                    f"{model}: {len(found['missing'])} missing, {len(found['extra'])} unrecorded, {len(found['changed'])} changed"
                )
                for key in found["missing"][:10]:
                    self.stdout.write(f"  missing from the table: {key}")
                for key in found["extra"][:10]:
                    self.stdout.write(f"  not in the history: {key}")
                for key, fields in list(found["changed"].items())[:10]:
                    self.stdout.write(f"  {key}: " + ", ".join(f"{field} {old!r} -> {new!r}" for field, (old, new) in fields.items()))
            raise CommandError("the replay differs from the live tables")
        if options["to"]:
            counts = replay.write_sqlite(options["to"], as_of=as_of)
            for model, count in sorted(counts.items()):
                self.stdout.write(f"{model}: {count}")
            self.stdout.write(
                f"written to {options['to']}; in a shell: from attendees.history.replay import open_sqlite; "
                f"open_sqlite({options['to']!r}); Model.objects.using('{replay.REPLAY_ALIAS}')"
            )
            return
        tables = replay.reconstruct(as_of=as_of)
        for model in sorted(tables):
            self.stdout.write(f"{model}: {len(tables[model])}")
