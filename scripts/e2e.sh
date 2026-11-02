#!/usr/bin/env bash
# End-to-end test against your own subscription.
#
#   1. Offline: unit tests, lint, Bicep and shell checks.
#   2. Baseline scan.
#   3. Create both test environments (waste + identity).
#   4. Rescan until every expected finding appears, or time out.
#   5. Always clean up, even on failure or Ctrl-C.
#
# Cost: a few cents. Takes 5 to 10 minutes, mostly waiting for Resource Graph.
#   ./scripts/e2e.sh                 # everything
#   SKIP_RBAC=1 ./scripts/e2e.sh     # skip the identity lab (needs no admin rights)
#   TIMEOUT=900 ./scripts/e2e.sh     # wait longer for indexing
set -euo pipefail

SKIP_RBAC=${SKIP_RBAC:-0}
TIMEOUT=${TIMEOUT:-600}
INTERVAL=30
REPORT=e2e.report.json
export GOV_SUBSCRIPTION_IDS=${GOV_SUBSCRIPTION_IDS:-$(az account show --query id -o tsv)}

step() { printf '\n==> %s\n' "$*"; }

cleanup() {
  step "Cleaning up"
  [[ -f .rbac-lab.env ]] && ./scripts/remove-rbac-lab.sh || true
  az group delete -n rg-gov-lab --yes --no-wait 2>/dev/null && echo "Deleting rg-gov-lab" || true
}

step "Offline checks"
pytest -q
ruff check .
if az bicep version >/dev/null 2>&1; then
  az bicep build --file infra/main.bicep --stdout >/dev/null && echo "Bicep OK"
fi
command -v shellcheck >/dev/null && shellcheck -S warning scripts/*.sh && echo "Shell scripts OK"

step "Subscription: $(az account show --query name -o tsv) ($GOV_SUBSCRIPTION_IDS)"

step "Baseline scan"
python -m governance.cli --json baseline.report.json

trap cleanup EXIT
step "Creating waste test environment"
./scripts/create-lab.sh
RBAC_FLAG=""
if [[ "$SKIP_RBAC" != "1" ]]; then
  step "Creating identity test environment"
  ./scripts/create-rbac-lab.sh
  # shellcheck source=/dev/null
  set -a && source .rbac-lab.env && set +a
  RBAC_FLAG="--rbac"
fi

step "Waiting for findings (up to ${TIMEOUT}s)"
deadline=$((SECONDS + TIMEOUT))
until python -m governance.cli --json "$REPORT" >/dev/null \
      && python scripts/check_report.py "$REPORT" $RBAC_FLAG --quiet; do
  if (( SECONDS >= deadline )); then
    step "Timed out. Results so far:"
    python scripts/check_report.py "$REPORT" $RBAC_FLAG || true
    exit 1
  fi
  echo "  not all findings indexed yet; retrying in ${INTERVAL}s"
  sleep "$INTERVAL"
done

step "Results"
python scripts/check_report.py "$REPORT" $RBAC_FLAG
python -m governance.cli
echo
echo "End-to-end test PASSED"
