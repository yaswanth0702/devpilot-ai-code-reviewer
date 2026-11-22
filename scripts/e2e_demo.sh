#!/usr/bin/env bash
# End-to-end demo of GitHub mode with NO real GitHub account or API key:
# fake GitHub API -> signed webhook -> Spring Boot gateway -> Python agent -> review posted back.
# Usage: scripts/e2e_demo.sh [provider]   (default: mock; use anthropic/openai with a key set)
set -euo pipefail
cd "$(dirname "$0")/.."
PROVIDER="${1:-mock}"
SECRET="demo-secret"
LOGS="$(mktemp -d)"
pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT

wait_for() { for _ in $(seq 1 60); do curl -sf "$1" >/dev/null && return 0; sleep 1; done; echo "timeout: $1"; exit 1; }

echo "==> building gateway"
(cd gateway && mvn -q -B package -DskipTests)

echo "==> starting fake GitHub on :9000"
python3 scripts/fake_github.py >"$LOGS/github.log" 2>&1 & pids+=($!)

echo "==> starting agent on :8000 (provider=$PROVIDER)"
(cd agent && GITHUB_API_URL=http://localhost:9000 GITHUB_TOKEN=fake DEVPILOT_PROVIDER="$PROVIDER" \
  python3 -m uvicorn devpilot_agent.app:app --port 8000 >"$LOGS/agent.log" 2>&1) & pids+=($!)

echo "==> starting gateway on :8080"
GITHUB_API_URL=http://localhost:9000 GITHUB_TOKEN=fake GITHUB_WEBHOOK_SECRET="$SECRET" AGENT_URL=http://localhost:8000 \
  java -jar gateway/target/devpilot-gateway-1.0.0.jar >"$LOGS/gateway.log" 2>&1 & pids+=($!)

wait_for http://localhost:9000/_reviews
wait_for http://localhost:8000/health
wait_for http://localhost:8080/actuator/health

PAYLOAD='{"action":"opened","pull_request":{"number":42,"draft":false,"head":{"sha":"3f2a9c1e0b7d4a5f8e6c2b1a0d9e8f7c6b5a4d3e"}},"repository":{"name":"demo","owner":{"login":"yaswanth0702"}}}'
SIG="sha256=$(printf '%s' "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $NF}')"

echo "==> sending signed pull_request webhook"
curl -s -X POST http://localhost:8080/webhooks/github \
  -H "Content-Type: application/json" -H "X-GitHub-Event: pull_request" \
  -H "X-GitHub-Delivery: demo-$(date +%s)" -H "X-Hub-Signature-256: $SIG" -d "$PAYLOAD"; echo

echo "==> waiting for the review job"
for _ in $(seq 1 60); do
  status=$(curl -s http://localhost:8080/api/reviews | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['status'])")
  [[ "$status" == "DONE" || "$status" == "FAILED" ]] && break; sleep 1
done

echo; echo "==> job record (gateway /api/reviews)"
curl -s http://localhost:8080/api/reviews | python3 -m json.tool
echo; echo "==> review DevPilot posted to the (fake) GitHub PR"
curl -s http://localhost:9000/_reviews | python3 -m json.tool
echo; echo "logs in $LOGS"
