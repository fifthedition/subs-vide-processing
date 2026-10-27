"""Owner/editor sessions and separately revocable renderer credentials."""
from http.cookies import SimpleCookie
import hashlib
import hmac
import json
import re
import secrets
import threading
import time

from studio import ValidationError, ConflictError, uid, now


class AccessError(Exception):
    def __init__(self, message="Sign in to continue.", status=401):
        self.status = status
        super().__init__(message)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValidationError("Use a password of 12–256 characters.")
    salt = salt or secrets.token_hex(16)
    result = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
    return salt + ":" + result.hex()


class Security:
    COOKIE = "studio_session"

    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.attempts = {}
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE,role TEXT,password TEXT,enabled INTEGER);
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT,csrf TEXT,expires REAL);
                CREATE TABLE IF NOT EXISTS workers(id TEXT PRIMARY KEY,name TEXT,token TEXT,enabled INTEGER,last_seen TEXT);
            """)
            if not db.execute("SELECT 1 FROM users").fetchone():
                path = store.directory / "setup-code"
                if not path.exists():
                    with path.open("x") as handle:
                        import os
                        os.chmod(path, 0o600)
                        handle.write(secrets.token_urlsafe(32))
                db.execute("INSERT OR REPLACE INTO settings VALUES('setup_hash',?)", (digest(path.read_text().strip()),))

    def needs_setup(self):
        with self.store.connection() as db:
            return not bool(db.execute("SELECT 1 FROM users").fetchone())

    def limit(self, key):
        with self.lock:
            moment = time.time()
            self.attempts = {k: v for k, v in self.attempts.items() if v[1] > moment - 600}
            count, _ = self.attempts.get(key, (0, moment))
            if count >= 12:
                raise AccessError("Too many attempts. Try again in ten minutes.", 429)
            self.attempts[key] = (count + 1, moment)

    def create_user(self, payload, setup=False):
        username = str(payload.get("username", "")).strip().lower()
        if not re.fullmatch(r"[a-z0-9_.@-]{3,80}", username):
            raise ValidationError("Use a username of 3–80 letters, digits, dots, dashes or @.")
        role = "owner" if setup else "editor"
        hashed = password_hash(payload.get("password"))
        user = {"id": uid(), "username": username, "role": role}
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if setup:
                row = db.execute("SELECT value FROM settings WHERE key='setup_hash'").fetchone()
                if db.execute("SELECT 1 FROM users").fetchone() or not row or not hmac.compare_digest(row[0], digest(str(payload.get("code", "")))):
                    raise AccessError("The setup code is invalid or has already been used.", 403)
            if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                raise ConflictError("That username already exists.")
            db.execute("INSERT INTO users VALUES(?,?,?,?,1)", (user["id"], username, role, hashed))
            if setup:
                db.execute("DELETE FROM settings WHERE key='setup_hash'")
        if setup:
            (self.store.directory / "setup-code").unlink(missing_ok=True)
        return user

    def login(self, payload):
        username = str(payload.get("username", "")).strip().lower()
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM users WHERE username=? AND enabled=1", (username,)).fetchone()
        password = payload.get("password", "")
        salt = row["password"].split(":")[0] if row else "00" * 16
        try:
            hashed = password_hash(password, salt)
        except ValidationError:
            raise AccessError("Incorrect username or password.") from None
        if not row or not hmac.compare_digest(hashed, row["password"]):
            raise AccessError("Incorrect username or password.")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.store.connection() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (digest(token), row["id"], csrf, time.time() + 12 * 3600))
        return token, {"id": row["id"], "username": username, "role": row["role"], "csrf": csrf}

    def session(self, cookie):
        cookies = SimpleCookie()
        try:
            cookies.load(cookie or "")
            token = cookies[self.COOKIE].value
        except (KeyError, ValueError):
            raise AccessError() from None
        with self.store.connection() as db:
            row = db.execute("SELECT u.id,u.username,u.role,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.enabled=1", (digest(token), time.time())).fetchone()
        if not row:
            raise AccessError()
        return dict(row)

    def logout(self, cookie):
        cookies = SimpleCookie(cookie or "")
        if self.COOKIE in cookies:
            with self.store.connection() as db:
                db.execute("DELETE FROM sessions WHERE token=?", (digest(cookies[self.COOKIE].value),))

    def users(self):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute("SELECT id,username,role,enabled FROM users ORDER BY username")]

    def disable_user(self, user_id):
        with self.store.connection() as db:
            db.execute("UPDATE users SET enabled=0 WHERE id=? AND role='editor'", (user_id,))
            db.execute("DELETE FROM sessions WHERE user_id=? AND user_id IN (SELECT id FROM users WHERE enabled=0)", (user_id,))

    def add_worker(self, name):
        token = secrets.token_urlsafe(48)
        item = {"id": uid(), "name": str(name or "Mac renderer")[:100]}
        with self.store.connection() as db:
            db.execute("INSERT INTO workers VALUES(?,?,?,1,NULL)", (item["id"], item["name"], digest(token)))
        return {**item, "token": token}

    def worker(self, authorization):
        if not authorization.startswith("Bearer "):
            raise AccessError("A renderer credential is required.")
        with self.store.connection() as db:
            row = db.execute("SELECT id,name FROM workers WHERE token=? AND enabled=1", (digest(authorization[7:]),)).fetchone()
            if row:
                db.execute("UPDATE workers SET last_seen=? WHERE id=?", (now(), row["id"]))
        if not row:
            raise AccessError("Renderer credential was revoked or is invalid.")
        return dict(row)

    def workers(self):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute("SELECT id,name,enabled,last_seen FROM workers ORDER BY name")]

    def revoke_worker(self, worker_id):
        with self.store.connection() as db:
            db.execute("UPDATE workers SET enabled=0 WHERE id=?", (worker_id,))
