"""Derive the lowercased text a record is searched by.

The ``search_text`` column on searchable models (``attendees.persons.models.searchable``) is
filled from these functions on every save, and the backfill migration and the
``refresh_search_text`` command use the same functions, so the column means one thing
everywhere. Everything is lowercased in Python rather than in SQL so that a search matches the
same rows on every backend: SQLite's ``LIKE`` ignores case for ASCII letters only, and Han names
are matched exactly on both.
"""


def normalise(text):
    """Lowercase and collapse whitespace: what both the column and a search term go through."""
    return " ".join(str(text if text is not None else "").lower().split())


def _leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _leaves(item)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (str, int, float)):
        yield str(value)


def search_text_of(*parts):
    """Join the string and number leaves of the parts, lowercased, nested dicts and lists flattened.

    Each distinct leaf appears once, in first-seen order, so the column stays short and a term
    matches whether it was typed as a name, a phone number or a note.
    """
    words = []
    seen = set()
    for part in parts:
        for leaf in _leaves(part):
            leaf = normalise(leaf)
            if leaf and leaf not in seen:
                seen.add(leaf)
                words.append(leaf)
    return " ".join(words)


def attendee_full_name(first_name, last_name, last_name2, first_name2):
    """The display form of an attendee's name: western name, then the eastern one unspaced."""
    western = f"{first_name or ''} {last_name or ''}".strip()
    eastern = f"{last_name2 or ''}{first_name2 or ''}".strip()
    return f"{western} {eastern}".strip()


#: The sections of ``Attendee.infos`` a person is looked up by. The others hold ids, flags and
#: timestamps (schedulers, emergency contacts, updating attendees, progressions).
ATTENDEE_SEARCHED_SECTIONS = ("names", "contacts", "fixed")


def attendee_search_text(first_name, last_name, last_name2, first_name2, infos):
    infos = infos or {}
    return search_text_of(
        first_name,
        last_name,
        last_name2,
        first_name2,
        *(infos.get(section) for section in ATTENDEE_SEARCHED_SECTIONS),
    )
