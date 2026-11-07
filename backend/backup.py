"""A copy of the library that is safe to take while the platform runs.

    python -m backend.backup <folder> [--keep 14]

Copying `platform.db` as a file while it is being written can give a copy that does not open, and leaves out
what is still in `platform.db-wal`. SQLite's own backup takes both, consistently, and the copy is checked
before it counts. The newest `--keep` copies in the folder are kept, older ones deleted. On the home server
the nightly job (`server/backup.sh`) runs this inside the container and copies the result to the WD drive.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config

PREFIX = "platform-"


def backup(folder: Path, keep: int = 14) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{PREFIX}{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}.db"
    partial = target.with_suffix(".db.part")
    source = sqlite3.connect(f"{config.DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
    copy = sqlite3.connect(partial)
    try:
        source.backup(copy)
        verdict = copy.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        copy.close()
        source.close()
    if verdict != "ok":
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"The copy failed SQLite's integrity check: {verdict}")
    partial.replace(target)
    for old in sorted(folder.glob(f"{PREFIX}*.db"))[:-keep] if keep > 0 else []:
        old.unlink()
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy the library safely, also while the platform runs.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--keep", type=int, default=14, help="how many copies to keep in the folder")
    args = parser.parse_args()
    if not config.DB_PATH.is_file():
        print(f"There is no library at {config.DB_PATH}", file=sys.stderr)
        return 1
    try:
        target = backup(args.folder, args.keep)
    except (sqlite3.Error, RuntimeError, OSError) as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        return 1
    print(f"{target} ({target.stat().st_size / 1e6:.1f} MB, integrity ok)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
