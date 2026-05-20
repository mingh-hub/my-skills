#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
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
  if out=$("$@" 2>&1) && echo "$out" | grep -q "$expect"; then
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

# ── 1. Python environment ──
echo "[1/3] Python environment"
run_check "python3 available" python3 --version

# ── 2. Auto-discover all Python tools and run --help ──
echo ""
echo "[2/3] Python tools (auto-discovered)"

TOOLS=()
while IFS= read -r -d '' f; do
  TOOLS+=("$f")
done < <(find "$REPO_ROOT" -path '*/tools/*.py' -type f -print0 | sort -z)

if [ ${#TOOLS[@]} -eq 0 ]; then
  echo "  [FAIL] no Python tools found under */tools/*.py"
  FAIL=$((FAIL + 1))
else
  for tool in "${TOOLS[@]}"; do
    label="$(echo "$tool" | sed "s|$REPO_ROOT/||")"
    local_out=""
    if local_out=$(python3 "$tool" --help 2>&1); then
      echo "  [PASS] $label --help"
      PASS=$((PASS + 1))
    elif echo "$local_out" | grep -q "ModuleNotFoundError"; then
      mod=$(echo "$local_out" | grep "ModuleNotFoundError" | sed "s/.*No module named '//;s/'.*//")
      echo "  [SKIP] $label --help (missing module: $mod)"
    else
      echo "  [FAIL] $label --help"
      FAIL=$((FAIL + 1))
    fi
  done
fi

# ── Deep checks for tools that support safe modes ──
# cls_query.py: --no-browser produces JSON with cls_url
for tool in "${TOOLS[@]}"; do
  case "$(basename "$tool")" in
    cls_query.py)
      run_check_output "$(basename "$tool") --no-browser URL build" "cls_url" \
        python3 "$tool" --env prod --query 'serviceName:"order"' --no-browser
      ;;
  esac
done

# validate_query_anchors.py: parse any SKILL.md with anchor tables
for tool in "${TOOLS[@]}"; do
  if [ "$(basename "$tool")" = "validate_query_anchors.py" ]; then
    tool_dir="$(dirname "$tool")/.."
    while IFS= read -r -d '' skill_md; do
      skill_label="$(echo "$skill_md" | sed "s|$REPO_ROOT/||")"
      if grep -q '方法入口' "$skill_md" 2>/dev/null; then
        run_check "validate anchors: $skill_label" \
          python3 "$tool" --skill "$skill_md" --json
      fi
    done < <(find "$tool_dir" -name 'SKILL.md' -type f -print0 | sort -z)
  fi
done

# ── 3. Auto-discover YAML agent definitions ──
echo ""
echo "[3/3] Agent definitions (auto-discovered)"

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

# ── Summary ──
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
