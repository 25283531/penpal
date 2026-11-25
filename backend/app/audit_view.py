#!/usr/bin/env python3
"""Audited letter view (CLI) — same audit log as the /admin web view.

Decrypts ONE letter by id and prints its content to stdout. Every
view — including decrypt failures and refused key attempts — writes
one row to the append-only admin_audit_log table (time, operator,
action, letter id, reason, result; never letter content, never any
key material). If the audit write fails, nothing is printed and the
view is refused.

The decryption key must be presented for THIS view: --decryption-key
(paste the contents of .encryption.key), --key-file (path to the key
file), or, if neither is given, a hidden prompt. The presented key is
checked against the stored key's SHA256 fingerprint with a
constant-time comparison and is then used — not the stored key file —
to decrypt in memory only. A missing or wrong key is refused and the
attempt is audited (result key_missing / key_mismatch). The key value
is never printed and never written to the audit log. The server still
keeps its key file for reply generation; this gate applies to the
admin view path only.

Auth: the SAME admin password as /admin (scrypt hash in the settings
table). The password is never passed on the command line: set the
PENPAL_ADMIN_PASSWORD env var, or type it at the prompt.

Usage (inside the container):
  docker exec -it <container> python -m app.audit_view \\
      --letter-id 12 --reason 执法检查 --key-file /app/data/.encryption.key \\
      [--note "…"] [--operator zhangsan]

Reasons: 执法检查 / 用户申诉 / 故障排查 / 其他. Reason "其他"
requires --note. Exit codes: 0 ok, 2 bad usage / auth failed /
letter not found / key refused, 3 decrypt failed (audited),
4 audit-log write failed (view refused).
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import admin, crypto, database  # noqa: E402
from cryptography.fernet import InvalidToken  # noqa: E402


def _audit_key_failure(operator: str, letter_id: int, reason: str,
                       note: str | None, result: str) -> None:
    """Best-effort audit row for a refused key attempt. Carries no
    letter content and no key material — only the result."""
    try:
        database.record_audit_log(
            operator, "letter_view_failed", letter_id, reason, result, note,
        )
    except Exception:
        pass


def _read_presented_key(args) -> str | None:
    """The decryption key for this one view, from --decryption-key,
    --key-file, or a hidden prompt. Returns None when nothing was
    presented. The value is never printed."""
    if args.decryption_key:
        return args.decryption_key.strip() or None
    if args.key_file:
        try:
            return Path(args.key_file).read_text(encoding="utf-8").strip() or None
        except OSError as e:
            print(f"error: cannot read key file: {e}", file=sys.stderr)
            return None
    try:
        entered = getpass.getpass("解密密钥（粘贴 .encryption.key 里的内容）: ")
    except (EOFError, KeyboardInterrupt, OSError):
        return None
    return entered.strip() or None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audited letter view (CLI).")
    ap.add_argument("--letter-id", type=int, required=True)
    ap.add_argument("--reason", required=True,
                    help="执法检查 / 用户申诉 / 故障排查 / 其他")
    ap.add_argument("--note", default=None, help="Optional note (max 500 chars)")
    ap.add_argument("--operator", default="cli",
                    help="Operator name for the audit log (default: cli)")
    ap.add_argument("--decryption-key", default=None,
                    help="Decryption key for this view (paste the contents "
                         "of .encryption.key). Prefer --key-file.")
    ap.add_argument("--key-file", default=None,
                    help="Path to the .encryption.key file to use for this view")
    args = ap.parse_args(argv)

    if args.reason not in admin.AUDIT_REASONS:
        print(f"error: reason must be one of: {' / '.join(admin.AUDIT_REASONS)}",
              file=sys.stderr)
        return 2
    note = (args.note or "").strip() or None
    if note is not None and len(note) > 500:
        print("error: note must be at most 500 chars", file=sys.stderr)
        return 2
    if args.reason == "其他" and not note:
        print("error: reason '其他' requires --note", file=sys.stderr)
        return 2

    database.init_db()
    stored = database.get_setting("admin.password_hash", "")
    if not stored:
        print("error: admin password is not set (set it in /admin first)",
              file=sys.stderr)
        return 2
    password = os.environ.get("PENPAL_ADMIN_PASSWORD") or getpass.getpass("管理员密码: ")
    if not password or not admin.verify_password(password, stored):
        print("error: wrong admin password", file=sys.stderr)
        return 2
    operator = f"cli:{args.operator.strip() or 'cli'}"

    raw = database.get_letter_raw(args.letter_id)
    if raw is None:
        try:
            database.record_audit_log(
                operator, "letter_view_failed", args.letter_id,
                args.reason, "not_found", note,
            )
        except Exception:
            pass
        print(f"error: letter not found: {args.letter_id}", file=sys.stderr)
        return 2

    presented = _read_presented_key(args)
    if not presented:
        _audit_key_failure(operator, args.letter_id, args.reason, note,
                           "key_missing")
        print("error: decryption key required for this view "
              "(--decryption-key, --key-file, or paste at the prompt); "
              "attempt recorded in the audit log", file=sys.stderr)
        return 2
    if not crypto.presented_key_matches(presented):
        _audit_key_failure(operator, args.letter_id, args.reason, note,
                           "key_mismatch")
        presented = ""
        print("error: decryption key does not match the stored key; "
              "attempt recorded in the audit log", file=sys.stderr)
        return 2

    try:
        text = crypto.decrypt_text_with_key(raw["text_encrypted"], presented)
        result = "ok"
    except (InvalidToken, ValueError):
        text = None
        result = "decrypt_failed"
    finally:
        presented = ""  # drop the presented key as soon as decryption ends
    try:
        audit = database.record_audit_log(
            operator,
            "letter_view" if result == "ok" else "letter_view_failed",
            args.letter_id, args.reason, result, note,
        )
    except Exception as e:
        print(f"error: audit log write failed, view refused: {e}", file=sys.stderr)
        return 4
    if text is None:
        print("error: decrypt failed (key may have changed or data is "
              "corrupt); attempt recorded in the audit log",
              file=sys.stderr)
        return 3
    print(f"--- letter {args.letter_id} | {raw['character_id']} | "
          f"{raw['direction']} | {raw['created_at']} | audit #{audit['id']} ---")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
