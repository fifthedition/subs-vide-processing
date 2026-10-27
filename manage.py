#!/usr/bin/env python3
"""Local administrative recovery. Requires filesystem access to the NAS data."""
import argparse
import getpass
import os
from pathlib import Path

from security import password_hash
from studio import Store

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("action", choices=("reset-password",))
parser.add_argument("username")
parser.add_argument("--data", type=Path, default=Path("/data"))
options = parser.parse_args()
os.umask(0o077)
password = getpass.getpass("New password (12+ characters): ")
if password != getpass.getpass("Repeat password: "):
    raise SystemExit("Passwords did not match.")
hashed = password_hash(password)
store = Store(options.data)
with store.connection() as db:
    row = db.execute("SELECT id FROM users WHERE username=?", (options.username.strip().lower(),)).fetchone()
    if not row:
        raise SystemExit("Account not found.")
    db.execute("UPDATE users SET password=? WHERE id=?", (hashed, row["id"]))
    db.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
print("Password changed. All browser sessions for this account were signed out.")
