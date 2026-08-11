#!/usr/bin/env bash
# Push the rendered site to the public preview repo
# (peekbank/peekbank-datapage-preview) for team QA via GitHub Pages.
# Always full-renders first: single-file renders clobber _site resources.
set -euo pipefail
cd "$(dirname "$0")/.."

quarto render
rm -rf _site/repos
touch _site/.nojekyll

cd _site
git init -q -b main 2>/dev/null || true
git add -A
git -c user.name="peekbank-datapage" -c user.email="peekbank-dev@lists.stanford.edu" \
  commit -q -m "deploy $(date -u +%Y-%m-%dT%H:%M:%SZ)" || echo "nothing to commit"
git push -q --force https://github.com/peekbank/peekbank-datapage-preview.git main
echo "deployed: https://peekbank.github.io/peekbank-datapage-preview/"
