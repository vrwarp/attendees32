"""The merge truth table, written out rather than computed.

Deriving the expectations from the same logic under test would only prove the
code agrees with itself. Every row below was worked out by hand from the policy
and is meant to be re-checked by hand when the policy changes.

Neither Django nor a database is involved, so this file runs in a bare
interpreter -- which is the point of keeping ``merge.py`` pure.
"""

import pytest

from attendees.pcosync.merge import (
    AGREE,
    CONFLICT,
    MISSING,
    SKIP,
    TO_LOCAL,
    TO_PCO,
    baseline_after,
    decide,
    resolve_conflict,
)

A, B = "A", "B"


class Field:
    """The smallest thing ``decide()`` accepts: a key and a normaliser."""

    key = "demo"

    @staticmethod
    def compare_key(value):
        return value


FIELD = Field()


def base_map(value):
    return {} if value is MISSING else {FIELD.key: value}


# (local, pco, baseline) -> outcome
TRUTH_TABLE = [
    # --- the two sides already agree; the baseline cannot change that -------
    (A, A, A, AGREE),
    (A, A, B, AGREE),
    (A, A, None, AGREE),
    (A, A, MISSING, AGREE),
    (B, B, A, AGREE),
    (B, B, B, AGREE),
    (B, B, None, AGREE),
    (B, B, MISSING, AGREE),
    (None, None, A, AGREE),
    (None, None, B, AGREE),
    (None, None, None, AGREE),
    (None, None, MISSING, AGREE),

    # --- both sides hold a value, and they differ ---------------------------
    (A, B, A, TO_LOCAL),    # only Planning Center moved
    (A, B, B, TO_PCO),      # only attendees32 moved
    (A, B, None, CONFLICT),  # both filled a field that was empty
    (A, B, MISSING, CONFLICT),  # first run, no evidence either way
    (B, A, A, TO_PCO),
    (B, A, B, TO_LOCAL),
    (B, A, None, CONFLICT),
    (B, A, MISSING, CONFLICT),

    # --- attendees32 holds a value, Planning Center does not ----------------
    (A, None, A, SKIP),      # PCO cleared it; a sync does not clear
    (A, None, B, CONFLICT),  # local changed A, PCO cleared: both moved
    (A, None, None, TO_PCO),  # local filled an agreed-empty field
    (A, None, MISSING, TO_PCO),
    (B, None, A, CONFLICT),
    (B, None, B, SKIP),
    (B, None, None, TO_PCO),
    (B, None, MISSING, TO_PCO),

    # --- Planning Center holds a value, attendees32 does not ----------------
    (None, A, A, SKIP),       # local cleared it; a sync does not clear
    (None, A, B, CONFLICT),
    (None, A, None, TO_LOCAL),
    (None, A, MISSING, TO_LOCAL),
    (None, B, A, CONFLICT),
    (None, B, B, SKIP),
    (None, B, None, TO_LOCAL),
    (None, B, MISSING, TO_LOCAL),
]


def test_truth_table_is_exhaustive():
    """Three local values x three PCO values x four baselines."""
    assert len(TRUTH_TABLE) == 36
    assert len({(row[0], row[1], row[2]) for row in TRUTH_TABLE}) == 36


@pytest.mark.parametrize("local,pco,base,expected", TRUTH_TABLE)
def test_decide(local, pco, base, expected):
    decision = decide(FIELD, local, pco, base_map(base))
    assert decision.outcome == expected, (
        f"local={local!r} pco={pco!r} base={base!r} "
        f"gave {decision.outcome} ({decision.reason})"
    )


@pytest.mark.parametrize("local,pco,base,expected", TRUTH_TABLE)
def test_decide_carries_the_raw_values_for_the_report(local, pco, base, expected):
    decision = decide(FIELD, local, pco, base_map(base))
    assert decision.local == local
    assert decision.pco == pco
    assert decision.key == FIELD.key
    assert decision.reason


def test_a_sync_never_clears_in_either_direction():
    """The two SKIP shapes are the whole of rule 1, so they get their own test."""
    assert decide(FIELD, A, None, {FIELD.key: A}).outcome == SKIP
    assert decide(FIELD, None, A, {FIELD.key: A}).outcome == SKIP


def test_ignored_field_is_skipped_whatever_the_values():
    for local, pco, base, _ in TRUTH_TABLE:
        decision = decide(FIELD, local, pco, base_map(base), ignored={FIELD.key})
        assert decision.outcome == SKIP
        assert "ignored" in decision.reason


def test_ignoring_a_different_field_changes_nothing():
    decision = decide(FIELD, A, B, base_map(MISSING), ignored={"something_else"})
    assert decision.outcome == CONFLICT


def test_missing_baseline_is_not_the_same_as_an_empty_one():
    """A never-synced field and a field agreed to be empty behave differently."""
    assert decide(FIELD, A, B, {}).outcome == CONFLICT
    assert decide(FIELD, A, B, {FIELD.key: None}).outcome == CONFLICT
    # ...but where only one side holds a value they diverge:
    assert decide(FIELD, A, None, {}).outcome == TO_PCO
    assert decide(FIELD, A, None, {FIELD.key: A}).outcome == SKIP


def test_a_normaliser_that_folds_values_produces_agreement():
    class Folding:
        key = "folded"

        @staticmethod
        def compare_key(value):
            return value.lower() if isinstance(value, str) else value

    assert decide(Folding(), "Ann@Example.com", "ann@example.com", {}).outcome == AGREE


# --------------------------------------------------------------------------
# The baseline rule. Getting this wrong makes a conflict vanish on the next run.
# --------------------------------------------------------------------------

def test_baseline_is_stamped_only_on_agreement_or_an_applied_write():
    assert baseline_after(decide(FIELD, A, A, base_map(MISSING))) == (True, A)
    # PCO moved, we wrote its value locally: the new agreement is PCO's value.
    assert baseline_after(decide(FIELD, A, B, base_map(A))) == (True, B)
    # attendees32 moved, we pushed its value: the agreement is the local value.
    assert baseline_after(decide(FIELD, A, B, base_map(B))) == (True, A)


@pytest.mark.parametrize("local,pco,base", [(A, B, None), (A, B, MISSING)])
def test_a_conflict_never_earns_a_baseline(local, pco, base):
    decision = decide(FIELD, local, pco, base_map(base))
    assert decision.outcome == CONFLICT
    assert baseline_after(decision) == (False, None)


def test_a_skip_never_earns_a_baseline():
    decision = decide(FIELD, A, None, base_map(A))
    assert decision.outcome == SKIP
    assert baseline_after(decision) == (False, None)


def test_an_applied_write_settles_the_field_next_run():
    """A conflict resolved into a write must not reappear."""
    decision = decide(FIELD, A, B, base_map(A))
    assert decision.outcome == TO_LOCAL
    should_write, value = baseline_after(decision)
    assert should_write
    # attendees32 now holds B as well; the next run sees agreement.
    assert decide(FIELD, B, B, {FIELD.key: value}).outcome == AGREE


# --------------------------------------------------------------------------
# Resolution is a baseline edit, not a queued write.
# --------------------------------------------------------------------------

def test_keep_local_makes_the_next_run_push():
    conflict = decide(FIELD, A, B, base_map(MISSING))
    should_write, value = resolve_conflict(conflict, "keep_local")
    assert (should_write, value) == (True, B)
    assert decide(FIELD, A, B, {FIELD.key: value}).outcome == TO_PCO


def test_keep_pco_makes_the_next_run_pull():
    conflict = decide(FIELD, A, B, base_map(MISSING))
    should_write, value = resolve_conflict(conflict, "keep_pco")
    assert (should_write, value) == (True, A)
    assert decide(FIELD, A, B, {FIELD.key: value}).outcome == TO_LOCAL


def test_ignoring_touches_no_baseline():
    conflict = decide(FIELD, A, B, base_map(MISSING))
    assert resolve_conflict(conflict, "ignored") == (False, None)
