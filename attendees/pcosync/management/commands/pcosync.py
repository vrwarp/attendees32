"""Run a Planning Center sync from a shell.

Deliberately built before the button. It is scriptable, it is how the first
production run will actually be done, and the sync has to be trustworthy from a
terminal before it is something a volunteer can press.
"""

import pghistory
from django.core.management.base import BaseCommand, CommandError

from attendees.pcosync.models import PcoDivergence, PcoSyncRun
from attendees.pcosync.services.config import config_for, write_config
from attendees.pcosync.services.runner import run_sync
from attendees.whereabouts.models import Organization


class Command(BaseCommand):
    help = "Sync attendees with Planning Center through pcomirror."

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True,
                            help="Organization slug")
        parser.add_argument(
            "--mode", default=PcoSyncRun.DRY_RUN,
            choices=[value for value, _ in PcoSyncRun.MODES],
            help="dry_run plans and writes nothing; pull_only writes to "
                 "attendees32; full writes both ways; stamp_uuids writes only "
                 "the attendees_uuid custom field",
        )
        parser.add_argument("--limit", type=int, default=None,
                            help="stop after this many people")
        parser.add_argument(
            "--allow-push", action="store_true",
            help="temporarily turn on push_enabled for this run only",
        )
        parser.add_argument("--show", type=int, default=15,
                            help="how many divergences to print")

    def handle(self, *args, **options):
        organization = Organization.objects.filter(slug=options["org"]).first()
        if organization is None:
            raise CommandError(f"no organization with slug {options['org']!r}")

        config = config_for(organization)
        reason = config.blocking_reason()
        if reason:
            raise CommandError(
                f"{organization} cannot sync: {reason}. Settings live in "
                f'Organization.infos["settings"]["pcomirror"].'
            )

        restore = None
        if options["allow_push"] and not config.push_enabled:
            # Scoped to this invocation. A flag on the command line is a
            # deliberate act; leaving push on afterwards would not be.
            restore = config.push_enabled
            write_config(organization, {"push_enabled": True})
            self.stdout.write(self.style.WARNING(
                "push_enabled turned on for this run only"
            ))

        run = PcoSyncRun.objects.create(
            organization=organization, mode=options["mode"],
        )
        self.stdout.write(f"run {run.id}  mode={run.mode}  org={organization}")
        if config.dry_run and run.mode != PcoSyncRun.DRY_RUN:
            self.stdout.write(self.style.WARNING(
                "dry_run is on in this organization's settings, so nothing "
                "will be written whatever --mode says"
            ))

        try:
            with pghistory.context(modifier="pcomirror sync", run=str(run.id)):
                run_sync(run, limit=options["limit"])
        finally:
            if restore is not None:
                write_config(organization, {"push_enabled": restore})

        run.refresh_from_db()
        self.report(run, options["show"])

    def report(self, run, show):
        style = self.style.SUCCESS if run.state == PcoSyncRun.SUCCEEDED \
            else self.style.ERROR
        self.stdout.write(style(f"\n{run.state}  phase={run.phase}"))
        if run.error:
            self.stdout.write(self.style.ERROR(run.error))

        for key in sorted(run.counts or {}):
            self.stdout.write(f"  {key:24} {run.counts[key]}")

        divergences = PcoDivergence.objects.filter(
            organization=run.organization, resolution=PcoDivergence.OPEN,
            is_removed=False,
        )
        total = divergences.count()
        if not total:
            self.stdout.write(self.style.SUCCESS("\nno open divergences"))
            return

        self.stdout.write(f"\n{total} open divergence(s):")
        for divergence in divergences.order_by("kind", "pointer")[:show]:
            self.stdout.write(
                f"  [{divergence.severity}] {divergence.kind} "
                f"{divergence.pointer}\n"
                f"      attendees32={divergence.local_value!r} "
                f"planning-center={divergence.pco_value!r}\n"
                f"      {divergence.note}"
            )
        if total > show:
            self.stdout.write(f"  ... and {total - show} more")
