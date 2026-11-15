#!/usr/bin/env bash
# Build the code submission zip:  ./make_submission.sh <team_name>   ->  dist/<team_name>.zip
# Contains everything needed to install and run the code; excludes the venv, caches,
# the raw trace download and the planning notes.
set -euo pipefail
team="${1:?usage: ./make_submission.sh <team_name>}"
root="$(cd "$(dirname "$0")" && pwd)"
stage="$(mktemp -d)/$team"
mkdir -p "$stage" "$root/dist"

cd "$root"
for f in README.md requirements.txt pyproject.toml uv.lock .python-version main.py; do cp "$f" "$stage/"; done
for d in src experiments tests data results; do
  rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' --exclude 'raw/' "$d" "$stage/"
done

rm -f "$root/dist/$team.zip"
(cd "$(dirname "$stage")" && zip -qr "$root/dist/$team.zip" "$team")
echo "wrote dist/$team.zip ($(du -h "$root/dist/$team.zip" | cut -f1))"
