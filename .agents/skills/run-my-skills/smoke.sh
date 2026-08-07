#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
LOG_LOOKUP_ROOT="$REPO_ROOT/xh-smart/xh-log-lookup"
PASS=0
FAIL=0

run_check() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "  [PASS] $label"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $label"
    FAIL=$((FAIL + 1))
  fi
}

run_check_output() {
  local label="$1"
  local expect="$2"
  shift 2
  local out
  if out=$("$@" 2>&1) && [[ "$out" == *"$expect"* ]]; then
    echo "  [PASS] $label"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $label"
    echo "         output: ${out:0:200}"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== my-skills smoke test ==="
echo ""

# 1. Python environment
echo "[1/4] Python environment"
run_check "python3 available" python3 --version
run_check "Python 3.10+" python3 -c \
  'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'

# 2. Offline CLI/import checks
echo ""
echo "[2/4] xh-log-lookup offline CLI checks"

CLI_NAMES=(
  cls_log_query.py
  resolve_hermes_session.py
  resolve_workspace.py
  send_feishu_card.py
  source_inspect.py
  validate_query_anchors.py
)

for name in "${CLI_NAMES[@]}"; do
  run_check "scripts/$name --help" \
    env PYTHONDONTWRITEBYTECODE=1 python3 "$LOG_LOOKUP_ROOT/scripts/$name" --help
done

run_check "skill_config.py import" env \
  PYTHONDONTWRITEBYTECODE=1 LOG_LOOKUP_ROOT="$LOG_LOOKUP_ROOT" python3 -c '
import importlib.util
import os
from pathlib import Path
path = Path(os.environ["LOG_LOOKUP_ROOT"]) / "scripts" / "skill_config.py"
spec = importlib.util.spec_from_file_location("skill_config_smoke", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
'

run_check_output "cls_log_query.py WorkBuddy URL-only" '"source": "workbuddy"' \
  env PYTHONDONTWRITEBYTECODE=1 python3 "$LOG_LOOKUP_ROOT/scripts/cls_log_query.py" \
    --env prod --query 'serviceName:"order"' --method workbuddy

run_check_output "anchors are advisory without source" '"verification_status"' \
  env PYTHONDONTWRITEBYTECODE=1 python3 \
    "$LOG_LOOKUP_ROOT/scripts/validate_query_anchors.py" --all --json

# 3. Unit tests
echo ""
echo "[3/4] xh-log-lookup unit tests"
run_check "unittest discover" env PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s "$LOG_LOOKUP_ROOT/tests" -p 'test_*.py'

# 4. Auto-discover YAML agent definitions
echo ""
echo "[4/4] Agent definitions (auto-discovered)"

YAMLS=()
while IFS= read -r -d '' f; do
  YAMLS+=("$f")
done < <(find "$REPO_ROOT" -path '*/agents/*.yaml' -type f -print0 | sort -z)

if [ ${#YAMLS[@]} -eq 0 ]; then
  echo "  (none found)"
else
  for yaml in "${YAMLS[@]}"; do
    label="$(echo "$yaml" | sed "s|$REPO_ROOT/||")"
    run_check "$label parseable" python3 -c "
import sys
try:
    text = open('$yaml').read()
    assert 'name:' in text or 'display_name:' in text
except Exception as e:
    print(e, file=sys.stderr); sys.exit(1)
"
  done
fi

# Summary
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
