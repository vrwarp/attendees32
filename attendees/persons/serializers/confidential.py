from rest_framework import serializers


class ConfidentialSerializerMixin:
    """Adds ``secret`` to the serializer of a ``Confidential`` record.

    Read, it says whether the requesting user's attendee is among the record's viewers, which is
    what the "Secret?" box on the attendee page shows. Written true, it puts that attendee on the
    viewers list; written false, it takes them off. The list itself is ``viewers``.
    """

    def get_fields(self):
        fields = super().get_fields()
        fields["secret"] = serializers.BooleanField(required=False)
        return fields

    def _reader_id(self):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return user.attendee_uuid_str() if user is not None and hasattr(user, "attendee_uuid_str") else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        reader = self._reader_id()
        # viewers.all() rather than a filter, so a queryset that prefetched the viewers answers
        # from memory and a listing costs no query per row.
        data["secret"] = bool(reader) and any(str(viewer.pk) == reader for viewer in instance.viewers.all())
        return data

    def create(self, validated_data):
        secret = validated_data.pop("secret", None)
        return self._apply_secret(super().create(validated_data), secret)

    def update(self, instance, validated_data):
        secret = validated_data.pop("secret", None)
        return self._apply_secret(super().update(instance, validated_data), secret)

    def _apply_secret(self, instance, secret):
        reader = self._reader_id()
        if secret is None or not reader:
            return instance
        if secret:
            instance.viewers.add(reader)
        else:
            instance.viewers.remove(reader)
        return instance
