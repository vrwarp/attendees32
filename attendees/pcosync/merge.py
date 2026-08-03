"""Three-way merge for the Planning Center sync.

Nothing here imports Django, and nothing here performs I/O. Given what
attendees32 holds, what Planning Center holds, and what the two last agreed on,
this module decides which way a field should move -- or that it should not move
at all. If ``decide()`` is wrong then every write the sync makes is wrong, so it
is kept small enough to hold in your head and tested exhaustively.

The policy is *never auto-resolve*. When both sides have moved since the last
agreement, neither side wins: the field is reported and left alone. That is the
whole reason a baseline exists. Without one you can only see *that* two values
differ; with one you can see *who moved*, which is the only thing that makes an
automatic write safe.

Two rules carry most of the weight and both are easy to lose in a refactor:

1. **A sync never clears.** A transition from a known value to nothing is not
   propagated, in either direction. Real data is deleted by people, on purpose,
   in one system at a time; a sync that mirrors an absence will eventually
   mirror an accident.

2. **A baseline is only stamped on agreement or on a write that succeeded.**
   Stamping one on a conflict makes the next run see "neither side changed" and
   mis-file the same disagreement for ever.
"""

from dataclasses import dataclass
from typing import Any, Iterable


class _Missing:
    """A baseline entry that has never been written.

    Distinct from ``None``, which means "this field is empty on both sides and
    we know it". ``MISSING`` means "we have no idea what these two last agreed
    on", and that difference decides whether a disagreement is a conflict or
    simply a first fill.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging affordance
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()

AGREE = "agree"
TO_LOCAL = "to_local"
TO_PCO = "to_pco"
CONFLICT = "conflict"
SKIP = "skip"

#: Outcomes that represent a value moving somewhere.
APPLYING = frozenset({TO_LOCAL, TO_PCO})


@dataclass(frozen=True)
class Decision:
    """What should happen to one field of one person.

    ``local``/``pco`` are the raw values, kept for the divergence report so a
    human sees what they would actually see in each system. ``local_key``,
    ``pco_key`` and ``base_key`` are the compare-normalised forms -- what the
    algorithm reasoned about and what a baseline stores.
    """

    key: str
    outcome: str
    reason: str
    local: Any = None
    pco: Any = None
    local_key: Any = None
    pco_key: Any = None
    base_key: Any = MISSING

    @property
    def is_conflict(self) -> bool:
        return self.outcome == CONFLICT

    @property
    def writes_local(self) -> bool:
        return self.outcome == TO_LOCAL

    @property
    def writes_pco(self) -> bool:
        return self.outcome == TO_PCO


def decide(field, local, pco, base_map, ignored: Iterable[str] = ()) -> Decision:
    """Decide the fate of one field.

    :param field: anything carrying ``.key`` and ``.compare_key(value)``. Typed
        structurally on purpose so this module never imports the mapping table,
        which is what keeps it testable without Django.
    :param local: the raw attendees32 value.
    :param pco: the raw Planning Center value.
    :param base_map: ``{field_key: compare-normalised value}`` from the last
        agreement. A key absent from it is ``MISSING``, not ``None``.
    :param ignored: field keys a human has told us to stop reporting.
    """
    if field.key in ignored:
        return _decision(
            field, SKIP, "a human marked this field ignored for this person",
            local, pco, MISSING,
        )

    local_key = field.compare_key(local)
    pco_key = field.compare_key(pco)
    base_key = base_map.get(field.key, MISSING) if base_map else MISSING

    if local_key == pco_key:
        reason = (
            "neither side holds a value"
            if local_key is None
            else "both sides hold the same value"
        )
        return _decision(field, AGREE, reason, local, pco, base_key,
                         local_key, pco_key)

    if base_key is MISSING:
        # No record of a previous agreement. One side being empty is a first
        # fill and is safe; both sides holding different values is genuinely
        # ambiguous, and on a first run there will be a lot of these. That is
        # the policy working, not the sync being broken.
        if local_key is None:
            return _decision(field, TO_LOCAL, "attendees32 held nothing",
                             local, pco, base_key, local_key, pco_key)
        if pco_key is None:
            return _decision(field, TO_PCO, "Planning Center held nothing",
                             local, pco, base_key, local_key, pco_key)
        return _decision(
            field, CONFLICT,
            "no record of a previous agreement, and the two differ",
            local, pco, base_key, local_key, pco_key,
        )

    local_changed = local_key != base_key
    pco_changed = pco_key != base_key

    if local_changed and pco_changed:
        return _decision(field, CONFLICT, "both sides changed since the last sync",
                         local, pco, base_key, local_key, pco_key)

    if local_changed:
        if local_key is None:
            return _decision(field, SKIP,
                             "attendees32 cleared it; a sync does not clear",
                             local, pco, base_key, local_key, pco_key)
        return _decision(field, TO_PCO,
                         "attendees32 changed it; Planning Center did not",
                         local, pco, base_key, local_key, pco_key)

    if pco_changed:
        if pco_key is None:
            return _decision(field, SKIP,
                             "Planning Center cleared it; a sync does not clear",
                             local, pco, base_key, local_key, pco_key)
        return _decision(field, TO_LOCAL,
                         "Planning Center changed it; attendees32 did not",
                         local, pco, base_key, local_key, pco_key)

    # Unreachable: both sides equal to the baseline implies they equal each
    # other, which the agreement branch above already returned. Kept so a future
    # edit that breaks that invariant fails loudly instead of falling off the end.
    return _decision(field, CONFLICT, "the recorded agreement matches neither side",
                     local, pco, base_key, local_key, pco_key)


def _decision(field, outcome, reason, local, pco, base_key,
              local_key=None, pco_key=None) -> Decision:
    return Decision(
        key=field.key, outcome=outcome, reason=reason,
        local=local, pco=pco,
        local_key=local_key, pco_key=pco_key, base_key=base_key,
    )


def baseline_after(decision: Decision):
    """The baseline entry a decision earns, as ``(should_write, value)``.

    Call this *after* a write has actually succeeded, never before. A conflict
    and a skip earn nothing, and so does a write that raised -- leaving the old
    entry in place is what lets the next run see the disagreement again.
    """
    if decision.outcome == AGREE:
        return True, decision.local_key
    if decision.outcome == TO_LOCAL:
        # attendees32 now holds what Planning Center held; that is the new
        # agreement.
        return True, decision.pco_key
    if decision.outcome == TO_PCO:
        return True, decision.local_key
    return False, None


def resolve_conflict(decision: Decision, resolution: str):
    """Turn a human's choice into a baseline edit, as ``(should_write, value)``.

    Resolving a conflict needs no pending-write queue: moving the baseline to
    the side that *loses* makes the next ordinary run see exactly one side as
    changed, and it applies the winner through the normal path. "Keep the local
    value" therefore records Planning Center's value as the agreement.
    """
    if resolution == "keep_local":
        return True, decision.pco_key
    if resolution == "keep_pco":
        return True, decision.local_key
    # "ignored" is recorded on the link's ignored_fields, not in the baseline.
    return False, None
