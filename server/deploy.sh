#!/usr/bin/env bash
# Puts the code of this folder on the home server and restarts the platform there with it.
#
#   server/deploy.sh           wait for running scrapes to finish, copy, rebuild, restart, check it answers
#   server/deploy.sh --check   the same, and first run the tests inside the new image (on Linux, offline)
#   server/deploy.sh --now     do not wait for running scrapes (they are cut off and run again a minute later)
#
# Run it from WSL after a change has passed its tests and the dashboard is built (frontend/dist). It needs
# ssh to the server with a key. The library, the model and the keys on the server are never touched.
set -euo pipefail

SERVER="${NSP_SERVER:-jacob228@192.168.1.161}"
HOST="${SERVER#*@}"
PORT=8765
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECK=0
WAIT=1
for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --now) WAIT=0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

[[ -f "$HERE/frontend/dist/index.html" ]] || { echo "The dashboard is not built: run npm run build in frontend/ first." >&2; exit 1; }

running() {  # how many jobs are queued or running on the server; nothing when it does not answer
  curl -sf -m 5 "http://$HOST:$PORT/api/jobs" 2>/dev/null |
    python3 -c 'import json,sys; print(sum(j["status"] in ("queued","running") for j in json.load(sys.stdin)))' 2>/dev/null || true
}
if (( WAIT )); then
  for _ in $(seq 1 270); do  # at most 45 minutes: a day's round of scrapes, Reddit's slow ones included
    busy="$(running)"
    [[ -z "$busy" || "$busy" == 0 ]] && break
    echo "Waiting: $busy job(s) running on the server…"
    sleep 10
  done
fi

echo "Copying the code to $SERVER:~/news-platform/app"
rsync -rlt --delete --delete-excluded \
  --exclude='__pycache__/' --exclude='*.pyc' --exclude='.pytest_cache/' \
  --include='/backend/***' --include='/tests/***' --include='/server/***' \
  --include='/frontend/' --include='/frontend/dist/***' \
  --include='/run.py' --include='/requirements.txt' --include='/pytest.ini' \
  --exclude='*' \
  "$HERE/" "$SERVER:news-platform/app/"

ssh "$SERVER" CHECK="$CHECK" 'bash -s' <<'REMOTE'
set -euo pipefail
cd ~/news-platform
cp app/server/compose.yaml compose.yaml
docker compose build --quiet
if [[ "$CHECK" == 1 ]]; then
  echo "Running the tests in the new image (no network, no library, no keys)…"
  docker run --rm --network none -e NSP_ENV_FILE=/nonexistent news-platform python -m pytest -q -p no:cacheprovider
fi
docker compose up -d --force-recreate
for _ in $(seq 1 60); do
  if curl -sf -m 5 http://127.0.0.1:8765/api/stats >/dev/null; then
    echo "The platform answers: $(curl -s http://127.0.0.1:8765/api/stats | cut -c1-120)"
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 2
done
echo "The platform did not answer within two minutes. Its log:" >&2
docker compose logs --tail 40 >&2
exit 1
REMOTE
