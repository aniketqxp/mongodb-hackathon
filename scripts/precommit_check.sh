#!/usr/bin/env bash
# Pre-commit checks: secret scan, domain-word scan of core/, tests. Exit non-zero on failure.
set -u
cd "$(git rev-parse --show-toplevel)"
fail=0

echo "== 1. secret scan (staged + tracked files)"
pat='(gsk_[A-Za-z0-9]{20,}|sk-or-[A-Za-z0-9-]{20,}|sk-[A-Za-z0-9]{32,}|lsv2_[A-Za-z0-9_]{20,}|mongodb(\+srv)?://[^ <]+:[^ <@]+@|AKIA[0-9A-Z]{16}|xi-api-key|pa-[A-Za-z0-9_-]{30,})'
if git ls-files -co --exclude-standard | grep -v '^scripts/precommit_check.sh$' | xargs -r grep -InE "$pat" 2>/dev/null; then
  echo "FAIL: possible secret above. Remove it and rotate the key."; fail=1
else echo "ok"; fi
if git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v '\.env\.example$'; then
  echo "FAIL: .env file is tracked"; fail=1
fi

echo "== 2. domain words in core/"
if [ -d core ]; then
  words=$(paste -sd'|' scripts/domain_words.txt)
  if grep -rInEi --exclude-dir=fixtures --exclude='.gitkeep' "\b($words)" core 2>/dev/null; then
    echo "FAIL: domain words in core/. Move meaning into pack data."; fail=1
  else echo "ok"; fi
fi

echo "== 3. tests"
if ls tests core/tests eval/tests 2>/dev/null | grep -q .; then
  python -m pytest -q 2>&1 | tail -5 || fail=1
else echo "no tests yet"; fi

[ $fail -eq 0 ] && echo "PRECOMMIT OK" || echo "PRECOMMIT FAILED"
exit $fail
