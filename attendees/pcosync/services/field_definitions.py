"""Resolving the custom-field tab, by slug, at runtime.

Field definition ids are per-organization. The ones in this org's tab happen to
be 731529-732029, and writing those into the source would work right up until
somebody points the sync at a second organization, where the same slugs carry
entirely different numbers and the sync would cheerfully write Chinese names
into whatever field 731529 means there.

So: resolve by slug, every time, and cache the answer briefly.
"""

import logging

from django.core.cache import cache

from attendees.pcosync.services.config import REQUIRED_SLUGS

logger = logging.getLogger(__name__)

CACHE_PREFIX = "pcosync:fielddefs"
CACHE_TTL_SECONDS = 6 * 60 * 60


class MissingFieldDefinitions(Exception):
    """The tab does not carry the slugs the mapping needs.

    Raised before anything is written. A sync that ran anyway would produce a
    report full of "Planning Center held nothing" for every custom field, which
    reads like real data rather than like a misconfiguration.
    """

    def __init__(self, missing):
        self.missing = sorted(missing)
        super().__init__(
            "the Planning Center custom-field tab is missing: "
            + ", ".join(self.missing)
        )


class FieldDefinitions:
    """Two lookups over the same answer."""

    def __init__(self, by_slug):
        #: {slug: {"id": str, "data_type": str, "name": str}}
        self.by_slug = by_slug
        #: {id: slug} -- what PcoPersonView needs to read a datum.
        self.by_id = {entry["id"]: slug for slug, entry in by_slug.items()}

    def id_for(self, slug):
        entry = self.by_slug.get(slug)
        return entry["id"] if entry else None

    def data_type(self, slug):
        entry = self.by_slug.get(slug)
        return entry.get("data_type") if entry else None

    def missing(self, required=REQUIRED_SLUGS):
        return [slug for slug in required if slug not in self.by_slug]

    def require(self, required=REQUIRED_SLUGS):
        missing = self.missing(required)
        if missing:
            raise MissingFieldDefinitions(missing)
        return self

    def as_dict(self):
        return dict(self.by_slug)

    def __len__(self):
        return len(self.by_slug)


def cache_key(organization_id):
    return f"{CACHE_PREFIX}:{organization_id}"


def fetch(client, tab_id=None):
    """Read the tab from Planning Center.

    Filtering by ``tab_id`` when one is configured keeps a large organization's
    unrelated custom fields out of the answer; without it we read them all and
    pick by slug, which is correct but noisier.
    """
    query = {"per_page": 100}
    if tab_id:
        query["where"] = {"tab_id": tab_id}

    by_slug = {}
    for record in client.paginate_records("/field_definitions", query, per_page=100):
        attributes = record.get("attributes") or {}
        slug = attributes.get("slug")
        # A deleted definition still answers on the collection; its data is
        # gone, so treating it as live would mean writing into a dead field.
        if not slug or attributes.get("deleted_at"):
            continue
        by_slug[slug] = {
            "id": str(record.get("id")),
            "data_type": attributes.get("data_type"),
            "name": attributes.get("name"),
        }
    return FieldDefinitions(by_slug)


def resolve(client, organization_id, tab_id=None, force=False):
    """Cached ``fetch``. Six hours, because a tab changes about never."""
    key = cache_key(organization_id)
    if not force:
        cached = cache.get(key)
        if cached:
            return FieldDefinitions(cached)

    definitions = fetch(client, tab_id)
    cache.set(key, definitions.as_dict(), CACHE_TTL_SECONDS)
    return definitions


def invalidate(organization_id):
    """Drop the cache after a write that suggests it is stale.

    A 404 or 422 from a ``field_data`` write is the usual trigger: it most often
    means the definition id we held no longer exists.
    """
    cache.delete(cache_key(organization_id))
