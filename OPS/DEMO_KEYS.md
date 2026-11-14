# Demo keys: one set for the recording laptop

No secrets in this file. Values travel by direct message or a password manager, never in the repo or a channel.

**Recording laptop: Jasmine's.** She runs `ui/run_demo.sh --core --reseed`. Everyone else keeps their own keys and stays off the shared ones while she records.

| Var | Whose value on the demo laptop | Why |
| --- | --- | --- |
| `MONGODB_URI` | one shared Atlas DB user `demo` with the **Atlas admin** role | the core runs `collMod` and creates the vector index at startup; a read/write-only user fails with "not authorized" |
| `VOYAGE_API_KEY` | Greatness's key | vectors; if absent the core falls back to keyword search, results are identical |
| `GROQ_API_KEY` | one dedicated key (not anyone's dev key) | free tier is 30 RPM and 8K TPM; two people on one key during a take will trip the limit |
| `COMPILER_SHARED_SECRET` | any one value, same in core and compiler | mismatch gives 403 on every parent rule |
| `DIRECTIVE_PIN` | agreed PIN | empty means every PIN is refused |
| `LANGSMITH_API_KEY` | David's | only for `--trace` runs; keep `LANGSMITH_TRACING=false` otherwise |
| `LLM_PROVIDER`, `LLM_MODEL` | `groq`, `openai/gpt-oss-120b` | as `.env.example` |

## Steps
1. Greatness creates Atlas user `demo` (Database Access, Atlas admin) and adds the demo laptop's IP under Network Access. Venue Wi-Fi changes the IP, so re-add it on site.
2. Greatness sends Jasmine one `.env` by direct message (MONGODB_URI, VOYAGE_API_KEY, COMPILER_SHARED_SECRET, DIRECTIVE_PIN). David sends LANGSMITH_API_KEY. A fresh Groq key goes in last.
3. Jasmine: `source .venv/bin/activate && set -a; source .env; set +a`, then `ui/run_demo.sh --core --reseed`.
4. Dry run before the take: `python -m eval.retract_one --core http://localhost:8001` must print PASS.
5. Take: pause 3 s between sentences (Groq burst limit). Nobody else uses the demo Groq key or the `demo` DB user.

## After submission
Rotate everything: Atlas `demo` user password, Groq, Voyage, LangSmith keys. Remove `0.0.0.0/0` from Network Access if it was added. A password fragment was pasted in a chat on 2026-11-14; treat the earlier DB user's password as burned.
