"""What running on the home server relies on: a backup taken while the platform runs, keys outside the code."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from backend import backup, config, db


def test_a_backup_is_a_whole_checked_copy_and_old_ones_are_cleared(tmp_path):
    db.init()
    db.execute("INSERT INTO settings(key, value) VALUES ('backup_probe', '\"kept\"')")  # still in the WAL
    folder = tmp_path / "backups"
    for old in ("platform-2026-01-01-000000.db", "platform-2026-01-02-000000.db"):
        folder.mkdir(exist_ok=True)
        (folder / old).write_bytes(b"old")
    (folder / "notes.txt").write_text("not a backup")

    made = backup.backup(folder, keep=2)

    copy = sqlite3.connect(made)
    assert copy.execute("SELECT value FROM settings WHERE key = 'backup_probe'").fetchone() == ('"kept"',)
    assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    copy.close()
    assert sorted(p.name for p in folder.iterdir()) == ["notes.txt", "platform-2026-01-02-000000.db", made.name]
    db.execute("DELETE FROM settings WHERE key = 'backup_probe'")
    config.reset_cache()


def test_the_keys_file_can_live_outside_the_code(tmp_path):
    env_file = tmp_path / "config" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-test-outside\n")
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    env["NSP_ENV_FILE"] = str(env_file)
    out = subprocess.run([sys.executable, "-c", "from backend import config; print(config.ENV_FILE); print(config.api_key())"],
                         capture_output=True, text=True, env=env, cwd=Path(__file__).resolve().parent.parent, check=True)
    assert out.stdout.split() == [str(env_file), "sk-ant-test-outside"]
