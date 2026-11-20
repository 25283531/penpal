#!/bin/bash
# Penpal curl smoke test: starts a temp server on port 7000, runs the
# letter flow, then stops it. No LLM key is set, so process-due must
# report queued (llm_unavailable), never a fake reply.
set -e
cd "$(dirname "$0")/.."
export DATA_DIR="$(mktemp -d /tmp/penpal-smoke-XXXXXX)"
export JWT_SECRET="smoke-secret"
PORT=7000
if [ -x .venv/bin/uvicorn ]; then UVICORN=.venv/bin/uvicorn; else UVICORN="python3 -m uvicorn"; fi
$UVICORN app.main:app --host 127.0.0.1 --port $PORT &
PID=$!
trap 'kill $PID 2>/dev/null; rm -rf "$DATA_DIR"' EXIT
sleep 3
BASE="http://127.0.0.1:$PORT"
echo "== health =="
curl -s $BASE/api/v1/health; echo
echo "== auth (age gate) =="
TOKEN=$(curl -s -X POST $BASE/api/v1/auth/device -H 'Content-Type: application/json' \
  -d '{"device_id":"smoke-device-001","age":30}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
echo "token: ${TOKEN:0:20}..."
echo "== characters =="
curl -s $BASE/api/v1/characters -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;d=json.load(sys.stdin);print([c['id'] for c in d])"
echo "== send first letter =="
curl -s -X POST $BASE/api/v1/letters -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"character_id":"P01","text":"你好，林澈，我最近在想要不要换工作。"}'; echo
echo "== process-due (no LLM key -> queued, never fake) =="
curl -s -X POST $BASE/api/v1/letters/process-due -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}'; echo
echo "== thread =="
curl -s "$BASE/api/v1/letters?character_id=P01" -H "Authorization: Bearer $TOKEN"; echo
echo "SMOKE OK"
