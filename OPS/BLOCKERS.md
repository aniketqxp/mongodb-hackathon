# BLOCKERS (append-only)

Add a line when blocked. Never edit or delete old lines; add a `RESOLVED` line instead.
Format: `YYYY-MM-DD HH:MM | package | blocked on (who/what) | detail`

2026-11-14 14:00 | G1 | Aniket | needs repo collaborator invite (Write) for Greatness, David, Jasmine, so the push can happen
2026-11-14 14:31 | J1 | David (D1) / Greatness (contract) | CONTRACT v0.1 has no route for parent sentence -> directive; UI uses manual slots until D1 exposes one (proposed: POST /directives/compile {pack_id, scope_id, text} -> {directive})
2026-11-14 14:31 | J1 | Jasmine (J2) + Greatness (G2) | contract has no slate/feed route; UI shows ui/static/fixture.json until the J2 harness serves slates from the G2 catalog
2026-11-14 14:51 | J2 | Greatness (contract) | no route to read directives back (e.g. GET /directives?pack_id&scope_id); harness caches the ones POST /directives accepted, in-process only
2026-11-14 14:51 | J2 | Aniket (A3) | core gate needs item fields: harness now sends topic/maturity/tags in POST /events payload and pre-checks the gate; confirm the core gate reads payload fields + max_maturity from the scope_profile event
2026-11-14 14:51 | J2 | Greatness/Aniket | seed graph has decisions above the scope gate (dec_child_7_02/03 -> maturity 3 for max 1) and a maturity-3 watch for child_12 (vid_018); harness never shows them, but the recall scenario targets them. Intended?
