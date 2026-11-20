"""Photos shipped in the image — run with: python -m pytest tests/ -q

Covers: GET /api/v1/characters returns real photo URLs for all 5
characters (avatar + 3 life + 2 candid), every one of the 30 URLs
serves 200 image/jpeg from the in-image static dir, unknown ids /
filenames 404, and an already-deployed DB seeded when photos were
still pending is healed on startup (backfill in _seed_characters
plus the read-time fallback in _decode_character).
"""
import json
import os
import sqlite3
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="penpal-photos-test-")
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.characters import PHOTO_FILES, placeholder_photos  # noqa: E402
from app.main import app  # noqa: E402
from app import database  # noqa: E402

database.init_db()
client = TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _new_device(device_id: str, age: int = 30) -> str:
    r = client.post("/api/v1/auth/device", json={"device_id": device_id, "age": age})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_all_30_photo_urls_serve_jpeg():
    tok = _new_device("photos-device-001")
    r = client.get("/api/v1/characters", headers=_auth(tok))
    assert r.status_code == 200
    chars = {c["id"]: c for c in r.json()}
    assert set(chars) == {"P01", "P02", "P03", "P04", "P05"}
    seen: set[str] = set()
    for cid, c in chars.items():
        assert c["photo_status"] == "ready", cid
        urls = [c["photo_url"]]
        urls += [p["photo_url"] for p in c["photos"]]
        urls += [p["photo_url"] for p in c["candid_photos"]]
        assert len(urls) == 6, cid
        assert len(c["photos"]) == 3 and len(c["candid_photos"]) == 2, cid
        for url in urls:
            assert url.startswith(f"/static/photos/{cid}/"), (cid, url)
            assert url.rsplit("/", 1)[-1] in PHOTO_FILES, (cid, url)
            seen.add(url)
            resp = client.get(url)
            assert resp.status_code == 200, (cid, url, resp.status_code)
            assert resp.headers["content-type"].startswith("image/jpeg"), url
            assert len(resp.content) > 10_000, url  # a real photo, not an empty file
            assert "max-age=86400" in resp.headers.get("cache-control", ""), url
    assert len(seen) == 30  # 5 characters x 6 files, all distinct


def test_photo_404s():
    assert client.get("/static/photos/P06/avatar.jpg").status_code == 404
    assert client.get("/static/photos/P01/avatar.png").status_code == 404
    assert client.get("/static/photos/P01/does-not-exist.jpg").status_code == 404
    # (A literal ".." segment is normalized away by the HTTP client
    # before it reaches the server, so it is not asserted here; the
    # filename allowlist + is_file check still guard the server side.)


def test_old_pending_db_is_healed_on_startup(tmp_path):
    """Simulate a DB deployed before photos went live: rows carry
    photo_url NULL / status pending / placeholder photos. After a
    fresh init_db() on that same DB, the API must return real URLs."""
    from app.config import settings

    old_data, old_db = settings.DATA_DIR, settings.DB_PATH
    try:
        settings.DATA_DIR = tmp_path
        settings.DB_PATH = tmp_path / "penpal.db"
        database.init_db()  # seeds with real photos
        # rewind P01 to the old pending state, as a pre-photo deploy had it
        with database.connect() as conn:
            conn.execute(
                "UPDATE characters SET photo_url = NULL, photo_status = 'pending',"
                " photos = ?, candid_photos = NULL WHERE id = 'P01'",
                (json.dumps(placeholder_photos(), ensure_ascii=False),),
            )
        row = conn.execute(
            "SELECT photo_url, photo_status FROM characters WHERE id = 'P01'"
        ).fetchone()
        assert row[0] is None and row[1] == "pending"
        database.init_db()  # startup backfill must heal it
        healed = database.get_character("P01")
        assert healed["photo_url"] == "/static/photos/P01/avatar.jpg"
        assert healed["photo_status"] == "ready"
        assert len(healed["photos"]) == 3
        assert all(p["is_placeholder"] is False for p in healed["photos"])
        assert len(healed["candid_photos"]) == 2
    finally:
        settings.DATA_DIR, settings.DB_PATH = old_data, old_db
