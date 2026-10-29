"""The subject of a place, as the API names it: a content type id and an object id."""
from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from attendees.whereabouts.models import Place


class PlaceSubjectSerializerMixin:
    """Reads and writes ``content_type`` and ``object_id`` on a place serializer, translating
    them to and from the typed subject keys the model holds. A write that names a subject sets
    that key and clears the others; a write that names none leaves them alone."""

    def get_fields(self):
        fields = super().get_fields()
        fields["content_type"] = serializers.PrimaryKeyRelatedField(queryset=ContentType.objects.all(), required=False)
        fields["object_id"] = serializers.CharField(required=False, allow_blank=False, max_length=36)
        return fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        content_type = instance.content_type
        data["content_type"] = content_type.pk if content_type else None
        data["object_id"] = instance.object_id
        return data

    def validate(self, attrs):
        attrs = super().validate(attrs)
        content_type = attrs.pop("content_type", None)
        object_id = attrs.pop("object_id", None)
        if content_type is None and object_id is None:
            return attrs
        if content_type is None or object_id is None:
            raise serializers.ValidationError("content_type and object_id name a place's subject together.")
        try:
            attrs.update(Place.subject_values(content_type, object_id))
        except ValueError as error:
            raise serializers.ValidationError({"content_type": str(error)})
        return attrs
