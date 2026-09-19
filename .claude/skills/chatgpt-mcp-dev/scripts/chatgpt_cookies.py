#!/usr/bin/env python3
"""Export the browser's chatgpt.com cookies as Playwright-shaped JSON.

Companion to chatgpt_session.py: same cookie DB, same keyring decryption,
but the full cookie records (domain, path, flags, expiry) instead of one
Cookie header, so a Playwright context can be logged in without touching
the live browser profile. Nothing is written to disk by this module; the
caller decides where the JSON goes (stdout by default).

    chatgpt_cookies.py [--browser chromium|chrome|auto] > cookies.json
"""

import argparse
import json
import shutil
import sqlite3
import tempfile

import chatgpt_session as cs

# Chrome stores expiry as microseconds since 1601-01-01.
_EPOCH_DELTA_S = 11_644_473_600


def export(browser: str) -> list[dict]:
    db, app = cs.BROWSERS[browser]
    if not db.exists():
        cs.fail(f"{browser} cookie DB not found at {db}")
    decrypt = cs._make_decryptor(app)
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        shutil.copy2(db, tmp.name)
        con = sqlite3.connect(tmp.name)
        rows = con.execute(
            "SELECT host_key, name, value, encrypted_value, path, expires_utc, "
            "is_secure, is_httponly, samesite FROM cookies "
            "WHERE host_key LIKE '%chatgpt.com' OR host_key LIKE '%openai.com'"
        ).fetchall()
        con.close()
    same_site = {0: "None", 1: "Lax", 2: "Strict"}
    out = []
    for host, name, value, enc, path, exp, secure, httponly, ss in rows:
        cookie = {
            "name": name,
            "value": decrypt(enc) if enc else value,
            "domain": host,
            "path": path or "/",
            "secure": bool(secure),
            "httpOnly": bool(httponly),
            "sameSite": same_site.get(ss, "Lax"),
        }
        if exp:
            cookie["expires"] = exp / 1_000_000 - _EPOCH_DELTA_S
        out.append(cookie)
    if not any(c["name"].startswith("__Secure-next-auth.session-token") for c in out):
        cs.fail(
            f"no ChatGPT session cookie in {browser} (is it logged in to chatgpt.com?)"
        )
    return out


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export chatgpt.com cookies as Playwright JSON."
    )
    p.add_argument("--browser", choices=["auto", "chromium", "chrome"], default="auto")
    args = p.parse_args()
    cs.set_prog("chatgpt-cookies")
    print(json.dumps(export(cs.pick_browser(args.browser))))


if __name__ == "__main__":
    main()
