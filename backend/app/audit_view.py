#!/usr/bin/env python3
"""Audited letter view (CLI) — same audit log as the /admin web view.

Decrypts ONE letter by id and prints its content to stdout. Every
view — including decrypt failures — writes one row to the append-only
admin_audit_log table (time, operator, action, letter id, reason,
result; never letter content). If the audit write fails, nothing is
printed and the view is refused.

Auth: the SAME admin password as /admin (scrypt hash in the settings
table). The password is never passed on the command line: set the
PENPAL_ADMIN_PASSWORD env var, or type it at the prompt.

Usage (inside the container):
  docker exec -it <container> python -m app.audit_view \\
      --letter-id 12 --reason 执法检查 [--note "…"] [--operator zhangsan]

Reasons: 执法检查 / 用户申诉 / 故障排查 / 其他.
Exit codes: 0 ok, 2 bad usage / auth failed / letter not found,
3 decrypt failed (audited), 4 audit-log write failed (view refused).
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import admin, crypto, database  # noqa: E402
from cryptography.fernet import InvalidToken  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audited letter view (CLI).")
    ap.add_argument("--letter-id", type=int, required=True)
    ap.add_argument("--reason", required=True,
                    help="执法检查 / 用户申诉 / 故障排查 / 其他")
    ap.add_argument("--note", default=None, help="Optional note (max 500 chars)")
    ap.add_argument("--operator", default="cli",
                    help="Operator name for the audit log (default: cli)")
    args = ap.parse_args(argv)

    if args.reason not in admin.AUDIT_REASONS:
        print(f"error: reason must be one of: {' / '.join(admin.AUDIT_REASONS)}",
              file=sys.stderr)
        return 2
    note = (args.note or "").strip() or None
    if note is not None and len(note) > 500:
        print("error: note must be at most 500 chars", file=sys.stderr)
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

    try:
        text = crypto.decrypt_text(raw["text_encrypted"])
        result = "ok"
    except (InvalidToken, ValueError):
        text = None
        result = "decrypt_failed"
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
