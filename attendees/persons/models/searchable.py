from django.db import models

from attendees.utils.search_text import search_text_of


class Searchable(models.Model):
    """A model with a ``search_text`` column, filled on every save from ``search_text_parts()``.

    The column holds the lowercased text a record can be found by, so lists and pickers search a
    real column with a portable substring match (``SearchService``) instead of casting a JSON
    column to text. A subclass returns the values it should be found by from
    ``search_text_parts()``; nested dicts and lists are flattened to their leaves. Writes that
    skip ``save()``, such as ``queryset.update()``, leave the column stale until
    ``refresh_search_text`` runs.
    """

    search_text = models.TextField(blank=True, default="", editable=False)

    class Meta:
        abstract = True

    def search_text_parts(self):
        return [getattr(self, "infos", None)]

    def save(self, *args, **kwargs):
        self.search_text = search_text_of(*self.search_text_parts())
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "search_text" not in update_fields:
            kwargs["update_fields"] = {*update_fields, "search_text"}
        super().save(*args, **kwargs)
