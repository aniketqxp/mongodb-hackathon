# BLOCKERS (append-only)

Add a line when blocked. Never edit or delete old lines; add a `RESOLVED` line instead.
Format: `YYYY-MM-DD HH:MM | package | blocked on (who/what) | detail`

2026-11-14 14:00 | G1 | Aniket | needs repo collaborator invite (Write) for Greatness, David, Jasmine, so the push can happen
2026-11-14 14:34 | D1 | Greatness (contract) | please add compiler routes to CONTRACT (port 8002): POST /directives/compile {pack_id,scope_id,text} -> {directive,summary}; POST /directives/confirm {pack_id,scope_id,directive,pin} -> core /directives response. J1 PIN card needs them. Also add DIRECTIVE_PIN, BUILDER_PIN, CORE_API_URL, COMPILER_PACK_DIR (empty) to .env.example
2026-11-14 14:34 | D1 | Greatness (contract) | pack schema has no target vocabulary, so "unknown targets" cannot be checked from the pack. Compiler takes a per-pack vocab {kind: [values]} from <pack_id>.vocab.json; needs the G2 taxonomy in that shape. Using synthetic compiler/fixtures for now
2026-11-14 14:34 | D1 | Aniket (A3) | security: core POST /directives must not trust confirmed_by from any caller, or the PIN can be bypassed by calling core directly. Suggest accepting directives only from the compiler service (shared-secret header from env)
2026-11-14 14:34 | D1 | Greatness (mock, scripts) | mock /directives returns not_confirmed with HTTP 200 but the contract says 4xx (the compiler handles both). precommit_check.sh runs pytest only if tests/, core/tests or eval/tests exist; please add compiler/tests
2026-11-14 14:34 | D1 | Greatness/Aniket (keys) | no GROQ_API_KEY in David's .env, so the live LLM test is skipped; offline tests pass
