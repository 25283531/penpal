#!/usr/bin/env python3
"""Decrypt-export tool (law-enforcement / inspection path ONLY).

Bulk export only. For viewing ONE letter, prefer the audited path:
the /admin web console ("信件查看" tab, POST /api/v1/admin/letters/
{id}/view) or `python -m app.audit_view` — both force a reason and
write one row per view to the append-only admin_audit_log table.

This bulk tool still needs BOTH:
  1. the database file, and
  2. the encryption key file (DATA_DIR/.encryption.key, mode 0600).

Usage (run from backend/):
  python3 scripts/decrypt_export.py \
      --db data/penpal.db --key data/.encryption.key \
      --out /tmp/penpal-export.json --operator "zhangsan"

Every run appends ONE audit-log line (time, operator, which record types
were exported and how many rows — NEVER content) to the audit file
(default: <out>.audit.log). If the key file is lost, the encrypted data is
permanently unrecoverable — back the key file up separately from the DB.
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

TABLES = {
    "letters": "SELECT id, device_id, character_id, direction, text, status, reply_due_at, created_at FROM letters ORDER BY id",
    "memories": "SELECT id, device_id, character_id, kind, text, importance, created_at, updated_at FROM memories ORDER BY id",
    "persona": "SELECT device_id, character_id, relationship_stage, summary, interaction_count, created_at, updated_at FROM persona ORDER BY device_id, character_id",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Decrypt-export user content (audited).")
    ap.add_argument("--db", required=True, help="SQLite database file")
    ap.add_argument("--key", required=True, help="Encryption key file (.encryption.key)")
    ap.add_argument("--out", required=True, help="Output JSON file (decrypted records)")
    ap.add_argument("--types", default=",".join(TABLES),
                    help="Comma-separated record types (default: all)")
    ap.add_argument("--operator", required=True, help="Operator name for the audit log")
    ap.add_argument("--audit", default=None,
                    help="Audit log file (default: <out>.audit.log)")
    args = ap.parse_args()

    db_path = Path(args.db)
    key_path = Path(args.key)
    if not db_path.exists():
        print(f"error: database file not found: {db_path}", file=sys.stderr)
        return 2
    if not key_path.exists():
        print(f"error: key file not found: {key_path}", file=sys.stderr)
        return 2

    from cryptography.fernet import Fernet, InvalidToken

    fernet = Fernet(key_path.read_bytes().strip())
    wanted = [t.strip() for t in args.types.split(",") if t.strip()]
    unknown = [t for t in wanted if t not in TABLES]
    if unknown:
        print(f"error: unknown types: {', '.join(unknown)} (available: {', '.join(TABLES)})",
              file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    out: dict[str, list[dict]] = {}
    counts: dict[str, int] = {}
    for table in wanted:
        rows = []
        for r in conn.execute(TABLES[table]).fetchall():
            d = dict(r)
            field = "summary" if "summary" in d else "text"
            try:
                d[field] = fernet.decrypt(d[field].encode()).decode()
            except (InvalidToken, ValueError, KeyError):
                d[field] = None  # undecryptable (legacy plaintext already migrated away)
                d["_decrypt_failed"] = True
            rows.append(d)
        out[table] = rows
        counts[table] = len(rows)
    conn.close()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    audit_path = Path(args.audit) if args.audit else out_path.with_suffix(".audit.log")
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "operator": args.operator,
        "db": str(db_path),
        "out": str(out_path),
        "types": counts,
    }
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"exported {sum(counts.values())} records "
          f"({', '.join(f'{k}={v}' for k, v in counts.items())}) to {out_path}")
    print(f"audit entry appended to {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
