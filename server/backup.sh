#!/usr/bin/env bash
# Nightly copy of the News Scraper Platform's library. Installed on the server as
# /usr/local/bin/news-platform-backup.sh and run by /etc/cron.d/news-platform-backup (04:00 UTC, after the
# Immich and Seafile backups). The copy is made inside the running container with SQLite's own backup
# (python -m backend.backup), kept on the SSD (7), and mirrored to the WD drive (14) when it is plugged in.
set -uo pipefail

LOCAL=/opt/news-platform/data/backups   # /data/backups inside the container
WD=/mnt/sdc2
DEST="$WD/news-platform-backup"
log() { echo "$(date -u +%FT%TZ) $*"; }

if ! out="$(docker exec news-platform python -m backend.backup /data/backups --keep 7 2>&1)"; then
  log "FAILED: $out"
  exit 1
fi
log "made $out"
if mountpoint -q "$WD"; then
  if ! { mkdir -p "$DEST" && rsync -rt "$LOCAL/" "$DEST/"; }; then
    log "FAILED to copy to $DEST (it runs as root from cron; by hand, use sudo)"
    exit 1
  fi
  ls -1 "$DEST"/platform-*.db 2>/dev/null | head -n -14 | xargs -r rm --
  log "copied to $DEST ($(ls -1 "$DEST"/platform-*.db | wc -l) copies there)"
else
  log "the WD drive is not mounted: the copy is only on the SSD"
fi
