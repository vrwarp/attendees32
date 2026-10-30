"""Portability lint: application code uses the portable ORM only.

This is design principle 1 of the portability plan, enforced as a test so it runs wherever the
suite runs. Every Python file under ``attendees/`` and ``config/`` is scanned, except
migrations and tests, for the constructs that tie a query to one database vendor:

* imports from ``django.contrib.postgres``
* ``RawSQL(``, ``.raw(``, ``.extra(``
* ``connection.cursor(``

Today's sites are listed in ``portability_allowlist.txt``, one ``path:construct`` per line.
A new site fails the suite; the fix is to write the query with the portable ORM, or, when a
vendor-specific accelerator is genuinely wanted, to keep it behind one clearly named module
and add that module to the list with a reason. An allow-list entry that no longer matches
also fails, so the list can only shrink as the phases remove their entries.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).with_name("portability_allowlist.txt")
SCANNED = ("attendees", "config")
SKIPPED_PARTS = {"migrations", "tests", "node_modules", "static"}

CONSTRUCTS = {
    "postgres-import": re.compile(r"^\s*(from|import)\s+django\.contrib\.postgres"),
    "RawSQL": re.compile(r"\bRawSQL\("),
    ".raw(": re.compile(r"\.raw\("),
    ".extra(": re.compile(r"\.extra\("),
    "cursor": re.compile(r"\bconnections?(\[[^\]]+\])?\.cursor\("),
}


def scan():
    """Return ``{"path:construct": [line numbers]}`` for every hit in application code."""
    hits = {}
    for top in SCANNED:
        for path in sorted((ROOT / top).rglob("*.py")):
            relative = path.relative_to(ROOT)
            if SKIPPED_PARTS & set(relative.parts) or path.name == "conftest.py":
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                for construct, pattern in CONSTRUCTS.items():
                    if pattern.search(line):
                        hits.setdefault(f"{relative.as_posix()}:{construct}", []).append(number)
    return hits


def allowed():
    entries = set()
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            entries.add(entry)
    return entries


def test_no_new_vendor_specific_code():
    hits = scan()
    new = sorted(set(hits) - allowed())
    details = "\n".join(f"  {key} (lines {', '.join(map(str, hits[key]))})" for key in new)
    assert not new, (
        "Vendor-specific database code outside the allow-list. Write it with the portable ORM, "
        "or add the module to attendees/tests/portability_allowlist.txt with a reason:\n"
        + details
    )


def test_allowlist_has_no_stale_entries():
    stale = sorted(allowed() - set(scan()))
    assert not stale, (
        "These allow-list entries no longer match anything; remove them from "
        "attendees/tests/portability_allowlist.txt so the list keeps shrinking:\n  "
        + "\n  ".join(stale)
    )
