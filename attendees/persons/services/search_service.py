from django.db.models import Case, IntegerField, Q, Value, When
from rapidfuzz import fuzz, process

from attendees.utils.search_text import normalise


class SearchService:
    """One search behind every list and picker.

    ``contains()`` is the portable substring match on a ``search_text`` column, usable through
    joins. ``search()`` is for a queryset of searchable rows: the substring match first, and when
    that finds fewer than a handful, fuzzy ranking in Python over the whole queryset, which
    handles typos, romanisation variants and partial names the same way on every backend. A
    congregation has hundreds to a few thousand people, so ranking them all takes about a
    millisecond; a trigram index in SQL would only be worth adding past tens of thousands.
    """

    #: Fewer substring hits than this and the fuzzy ranking runs as well.
    FUZZY_WHEN_FEWER_THAN = 5
    #: rapidfuzz partial ratio, out of 100, below which a word of the term is not in a text. A
    #: word of four letters or more with one letter wrong, missing or extra scores at least this;
    #: a shorter word has to appear as typed.
    FUZZY_CUTOFF = 75
    FUZZY_LIMIT = 50
    #: Terms shorter than this, such as a single Han character, are matched by substring only.
    FUZZY_MINIMUM_TERM = 3

    @staticmethod
    def contains(field, term):
        """A ``Q`` matching rows whose ``field`` (a search_text column, possibly joined) contains
        the term; an empty term matches everything."""
        normalised = normalise(term)
        if not normalised:
            return Q()
        return Q(**{f"{field}__contains": normalised})

    @classmethod
    def search(cls, queryset, term, field="search_text"):
        normalised = normalise(term)
        if not normalised:
            return queryset
        hits = queryset.filter(**{f"{field}__contains": normalised})
        if len(normalised) < cls.FUZZY_MINIMUM_TERM or hits.count() >= cls.FUZZY_WHEN_FEWER_THAN:
            return hits
        keys = cls.rank(normalised, dict(queryset.values_list("pk", field)))
        if not keys:
            return hits
        by_rank = Case(
            *(When(pk=key, then=Value(rank)) for rank, key in enumerate(keys)),
            output_field=IntegerField(),
        )
        return queryset.filter(pk__in=keys).order_by(by_rank)

    @classmethod
    def rank(cls, term, texts):
        """The keys of the texts every word of the term nearly appears in, best match first.

        Each word is matched on its own against the whole text with rapidfuzz's partial ratio,
        so a typo in one word, a different word order or a romanisation that differs by a letter
        still finds the person, while a text is only as good as its weakest word: "Hannah Liu"
        does not match Hannah Huang on the strength of the first name, and a phone number or an
        email address has to appear as typed. A word is scored against
        the whole text, rather than the term against the text as WRatio does, because a record's
        text is many times longer than what is typed, and WRatio scales such a match down to
        below any useful cutoff. Ties are broken by the text, so people of one score come out in
        name order.
        """
        scores = None
        for word in term.split():
            # Fuzzy matching is for names. A phone number or an email address, a word with a
            # digit or an @ in it, has to appear as typed: nearly the same email is someone else's.
            cutoff = 100 if any(c.isdigit() or c == "@" for c in word) else cls.FUZZY_CUTOFF
            word_scores = {
                key: score
                for _text, score, key in process.extract(
                    word, texts, scorer=fuzz.partial_ratio, score_cutoff=cutoff, limit=None
                )
            }
            if scores is None:
                scores = word_scores
            else:
                scores = {key: min(score, word_scores[key]) for key, score in scores.items() if key in word_scores}
            if not scores:
                return []
        ranked = sorted(scores.items(), key=lambda item: (-item[1], texts[item[0]]))
        return [key for key, _score in ranked[: cls.FUZZY_LIMIT]]
