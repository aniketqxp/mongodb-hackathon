---
name: precommit-check
description: Run before every commit in this repo. Scans for secrets, checks core/ for domain words, runs tests.
---
Run `bash scripts/precommit_check.sh` from the repo root.
- If it prints `PRECOMMIT FAILED`, fix the reported lines. Never bypass by editing the script or the word list.
- A leaked key: remove it, add a line to `OPS/BLOCKERS.md`, tell the owner to rotate the key.
- A domain word in `core/`: move that meaning into pack data or into the harness.
Then commit with a Conventional Commit message (`feat:`, `fix:`, `chore:`, `docs:`, `test:`).
