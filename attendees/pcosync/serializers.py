from rest_framework import serializers

from attendees.pcosync.models import PcoDivergence, PcoSyncRun


class PcoSyncRunSerializer(serializers.ModelSerializer):
    percent = serializers.IntegerField(read_only=True)
    started_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PcoSyncRun
        fields = (
            "id", "mode", "state", "phase", "percent", "counts", "log",
            "error", "created", "started_at", "finished_at",
            "cancel_requested", "started_by_name",
        )
        read_only_fields = fields

    def get_started_by_name(self, instance):
        return str(instance.started_by) if instance.started_by_id else None


class PcoDivergenceSerializer(serializers.ModelSerializer):
    attendee_label = serializers.SerializerMethodField()
    attendee_id = serializers.CharField(source="attendee.id", read_only=True,
                                        default=None)

    class Meta:
        model = PcoDivergence
        fields = (
            "id", "kind", "pointer", "label", "severity", "note",
            "local_value", "pco_value", "baseline_value", "suggestion",
            "resolution", "pco_person_id", "attendee_id", "attendee_label",
            "first_seen_at", "last_seen_at",
        )
        read_only_fields = tuple(f for f in fields if f != "resolution")

    def get_attendee_label(self, instance):
        return instance.attendee.display_label if instance.attendee_id else None


class ResolveSerializer(serializers.Serializer):
    """The three ways a person can settle a disagreement.

    Note there is no "write this value" option, and that is not an oversight:
    resolving works by moving the baseline so the *next ordinary run* applies
    the winner through the normal path. One way for a value to move means one
    place for it to go wrong.
    """

    resolution = serializers.ChoiceField(choices=[
        PcoDivergence.KEEP_LOCAL, PcoDivergence.KEEP_PCO, PcoDivergence.IGNORED,
    ])


class LinkSerializer(serializers.Serializer):
    attendee_id = serializers.UUIDField()


class StartRunSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=[value for value, _ in PcoSyncRun.MODES],
        default=PcoSyncRun.DRY_RUN,
    )
