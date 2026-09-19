"""Reuse a local browser's logged-in chatgpt.com session from the terminal.

Shared by the `chatgpt-refresh` and `chatgpt-chats` tools. It reads the
chatgpt.com cookies from a local Chromium/Chrome profile (decrypting them with
the OS-crypt key from the GNOME keyring) and mints a short-lived access token
via /api/auth/session, so terminal scripts can call the same backend endpoints
the web app uses. Nothing is written to disk; the durable credential stays in
the browser's own cookie/keyring store.

Requires running as the desktop user (session D-Bus + unlocked GNOME keyring)
with the browser logged in to chatgpt.com.
"""

import json
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import NoReturn

BASE = "https://chatgpt.com"
UA = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)

# name -> (cookie DB, GNOME-keyring "application" attribute for the OS-crypt key)
BROWSERS = {
    "chromium": (
        Path.home() / ".config" / "chromium" / "Default" / "Cookies",
        "chromium",
    ),
    "chrome": (
        Path.home() / ".config" / "google-chrome" / "Default" / "Cookies",
        "chrome",
    ),
}

_prog = "chatgpt"


def set_prog(name: str) -> None:
    """Set the program name used in error messages."""
    global _prog
    _prog = name


def fail(msg: str) -> NoReturn:
    print(f"{_prog}: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _keyring_password(app: str) -> bytes:
    import dbus  # system python3 provides python-dbus

    bus = dbus.SessionBus()
    svc_obj = bus.get_object("org.freedesktop.secrets", "/org/freedesktop/secrets")
    service = dbus.Interface(svc_obj, "org.freedesktop.Secret.Service")
    _, session = service.OpenSession("plain", dbus.String("", variant_level=1))
    unlocked, locked = service.SearchItems(
        {"application": app, "xdg:schema": "chrome_libsecret_os_crypt_password_v2"}
    )
    items = list(unlocked) + list(locked)
    if locked:
        service.Unlock(locked)
    for path in items:
        item = dbus.Interface(
            bus.get_object("org.freedesktop.secrets", path),
            "org.freedesktop.Secret.Item",
        )
        try:
            return bytes(item.GetSecret(session)[2])
        except dbus.DBusException:
            continue
    fail(f"'{app}' key not found in the GNOME keyring (is the keyring unlocked?)")


def _make_decryptor(app: str):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    def derive(pw: bytes) -> bytes:
        return PBKDF2HMAC(
            algorithm=hashes.SHA1(),  # nosec B303
            length=16,
            salt=b"saltysalt",
            iterations=1,
        ).derive(pw)

    keys = {b"v10": derive(b"peanuts"), b"v11": derive(_keyring_password(app))}

    def decrypt(enc: bytes) -> str:
        key = keys.get(enc[:3])
        if key is None:
            fail(f"unexpected cookie encryption version {enc[:3]!r}")
        d = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
        pt = d.update(enc[3:]) + d.finalize()
        pad = pt[-1]
        pt = pt[:-pad] if 0 < pad <= 16 else pt
        for cand in (pt, pt[32:]):  # newer Chromium prepends a 32-byte domain hash
            try:
                s = cand.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if s and all(32 <= ord(c) < 127 for c in s):
                return s
        fail("could not decode a decrypted cookie value")

    return decrypt


def _cookie_header(browser: str) -> str:
    """Cookie header with every chatgpt.com cookie for one browser profile.

    Sending the whole jar (session token plus Cloudflare's __cf_bm / cf_clearance
    and the oai-* cookies) makes the request look like the browser; sending only
    the session token trips Cloudflare's bot check.
    """
    db, app = BROWSERS[browser]
    if not db.exists():
        fail(f"{browser} cookie DB not found at {db}")
    decrypt = _make_decryptor(app)
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        shutil.copy2(db, tmp.name)  # copy: the live DB is locked by the browser
        con = sqlite3.connect(tmp.name)
        rows = con.execute(
            "SELECT name, value, encrypted_value FROM cookies "
            "WHERE host_key LIKE '%chatgpt.com' ORDER BY name"
        ).fetchall()
        con.close()
    pairs, have_session = [], False
    for name, value, enc in rows:
        pairs.append(f"{name}={decrypt(enc) if enc else value}")
        if name.startswith("__Secure-next-auth.session-token"):
            have_session = True
    if not have_session:
        fail(
            f"no ChatGPT session cookie in {browser} (is it logged in to chatgpt.com?)"
        )
    return "; ".join(pairs)


def pick_browser(choice: str = "auto") -> str:
    """Return the browser to use; 'auto' picks one with a ChatGPT session."""
    if choice != "auto":
        return choice
    for name, (db, _) in BROWSERS.items():
        if not db.exists():
            continue
        try:
            with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
                shutil.copy2(db, tmp.name)
                con = sqlite3.connect(tmp.name)
                row = con.execute(
                    "SELECT 1 FROM cookies WHERE host_key LIKE '%chatgpt.com' "
                    "AND name LIKE '__Secure-next-auth.session-token%' LIMIT 1"
                ).fetchone()
                con.close()
            if row:
                return name
        except sqlite3.Error:
            continue
    fail("no logged-in ChatGPT session found in chromium or chrome")


class Session:
    """An authenticated ChatGPT web session driven from the terminal."""

    def __init__(self, browser: str = "auto"):
        self.browser = pick_browser(browser)
        self.cookie = _cookie_header(self.browser)
        status, data = self.call("/api/auth/session")
        info: dict = data if isinstance(data, dict) else {}
        self.token = info.get("accessToken") if status == 200 else None
        self.user_id = (info.get("user") or {}).get("id")
        if not self.token or not self.user_id:
            fail(
                f"could not authenticate (HTTP {status}); session cookie may be expired"
            )

    def call(
        self,
        path: str,
        method: str = "GET",
        payload=None,
        raw: bool = False,
        retries: int = 3,
    ):
        """Call a chatgpt.com endpoint. Returns (status, parsed-json-or-text).

        Cloudflare rate-limits bursts of requests with a 403 HTML page, so
        403/429/5xx are retried with a short backoff before giving up.
        """
        headers = {
            "Cookie": self.cookie,
            "User-Agent": UA,
            "Accept": "application/json",
        }
        token = getattr(self, "token", None)
        if token:
            headers["Authorization"] = "Bearer " + token
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            BASE + path, headers=headers, method=method, data=body
        )

        last = (0, {"error": "no attempt made"})
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310
                    text = r.read().decode()
                    return r.status, (text if raw else json.loads(text))
            except urllib.error.HTTPError as e:
                last = (e.code, {"error": e.read().decode()[:200]})
                if e.code not in (403, 429) and e.code < 500:
                    return last
            except urllib.error.URLError as e:
                last = (0, {"error": str(e)[:200]})
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))  # 2s, then 4s
        return last
