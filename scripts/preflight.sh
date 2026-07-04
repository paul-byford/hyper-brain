#!/usr/bin/env bash
# Honest-prerequisites gate for `brain up` (ARCHITECTURE.md section 13).
#
# Checks, in order: the required CLIs are installed, gcloud is authenticated
# (both user and application-default), a project is selected, billing is enabled,
# and the caller can enable services. On ANY failure it prints the EXACT command
# to fix it and exits non-zero. It never silently assumes access, and it never
# tries to do the things an organisation legitimately gates (project creation,
# billing/spend approval, API allow-listing) -- it detects and reports them.
set -euo pipefail

PROJECT="${1:-}"

fail() {
  printf '\n\033[31mPreflight failed:\033[0m %s\n' "$1" >&2
  printf '  Fix: \033[36m%s\033[0m\n\n' "$2" >&2
  exit 1
}

# 1. Required CLIs.
command -v gcloud >/dev/null 2>&1 || fail \
  "the gcloud CLI is not installed." \
  "install the Google Cloud CLI: https://cloud.google.com/sdk/docs/install"
command -v terraform >/dev/null 2>&1 || fail \
  "terraform is not installed." \
  "install Terraform: https://developer.hashicorp.com/terraform/install"

# 2. User authentication.
if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q .; then
  fail "gcloud has no active account." "gcloud auth login"
fi

# 3. Application Default Credentials (Terraform and the SDKs use these).
if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
  fail "no Application Default Credentials." "gcloud auth application-default login"
fi

# 4. A project is selected (argument wins, else gcloud config).
if [ -z "$PROJECT" ]; then
  PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
fi
if [ -z "$PROJECT" ] || [ "$PROJECT" = "(unset)" ]; then
  fail "no project selected." "gcloud config set project <YOUR_PROJECT_ID>  (or pass -Project)"
fi

# 5. The project exists and is reachable by this caller.
gcloud projects describe "$PROJECT" >/dev/null 2>&1 || fail \
  "project '$PROJECT' not found or not accessible to this account." \
  "check the id, or ask your admin for access to '$PROJECT'"

# 6. Billing is enabled (near-zero cost, but Cloud Run/Vertex need a billing account).
billing_enabled="$(gcloud billing projects describe "$PROJECT" \
  --format='value(billingEnabled)' 2>/dev/null || echo "")"
if [ "$billing_enabled" != "True" ]; then
  fail "billing is not enabled on '$PROJECT'." \
    "link a billing account: gcloud billing projects link $PROJECT --billing-account <ACCOUNT_ID>"
fi

# Provisioning roles are not pre-checked: gcloud has no clean per-permission test,
# and `terraform apply` reports any missing role exactly. Billing + a reachable
# project + valid ADC are the load-bearing gates.

printf '\033[32mPreflight OK\033[0m for project %s\n' "$PROJECT"
printf '  (provisioning roles are verified by terraform apply, which names any missing role.)\n' >&2
# Echo the resolved project so the caller can capture it.
echo "$PROJECT"
