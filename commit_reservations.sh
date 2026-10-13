#!/bin/bash
# docs/reservations の変更をコミットしてpushする（他のワークフローと同時にpushしても再試行して反映する）
set -u
MSG="${1:-Update reservations}"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A docs/reservations
if git diff --cached --quiet; then
  echo "変更なし"
  exit 0
fi
git commit -m "$MSG"
for i in 1 2 3 4 5; do
  if git pull --rebase && git push; then
    exit 0
  fi
  echo "push失敗($i/5)。再試行します"
  sleep $((RANDOM % 5 + 3))
done
echo "pushに失敗しました" >&2
exit 1
