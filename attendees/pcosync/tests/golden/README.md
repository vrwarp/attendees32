# Golden corpus

Sanitized request/response pairs recorded from a real Planning Center People
organization, copied from `pcomirror` at commit
`9993c30d0c9c61272264999d91c4c3361ea651c1` (`tests/golden/`).

These are recordings, not fixtures anybody wrote. That is the value: a
hand-written fixture encodes what we *think* the API returns, and every bug this
sync can have starts with that belief being slightly wrong. `field_definitions_collection.json`
carries the real custom-field tab this sync depends on -- `chinese_last_name`,
`chinese_first_name`, `baptized`, `believer`, `congregation`, `attendees_uuid`
-- including the gap at `sequence` 4, which is exactly the kind of detail an
invented fixture would tidy away.

Each file is `{"name", "request": {"method", "path", "query"}, "response": {"status", "body"}}`.
Ids are sanitized (`100001`...), so they are stable to assert against but mean
nothing outside these files.

This is a curated subset, not the whole corpus -- the parts that exercise custom
fields, households, includes, pagination edges and error envelopes. If you need
a shape that is not here, copy it from pcomirror rather than writing one.

**Note on `links.next`:** these were recorded against Planning Center directly,
so `links.next` is absolute (`https://api.planningcenteronline.com/...`).
pcomirror rewrites it to a mirror-relative path. The client must handle both,
which is why `FakeMirror` can serve either shape.

To refresh:

```bash
cp ../../../../pcomirror/tests/golden/<name>.json .
```
