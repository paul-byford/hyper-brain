# Controlled-profile resources (Option B): authored in the same config as personal,
# behind toggles, and proven by validate + policy checks in CI. They are NOT applied
# in the personal demo. Several require an Organization, so they cannot `plan`
# without one; that is expected and documented (IMPLEMENTATION-PLAN.md "Decisions
# locked"), and the static policy checks assert their presence instead.

# Project number is needed to place the project inside a VPC-SC perimeter. Only read
# when the perimeter is actually being created.
data "google_project" "this" {
  count      = var.enable_vpc_sc ? 1 : 0
  project_id = var.project_id
}

resource "google_access_context_manager_access_policy" "perimeter_policy" {
  count  = var.enable_vpc_sc ? 1 : 0
  parent = "organizations/${var.org_id}"
  title  = "${var.name_prefix}-access-policy"
}

resource "google_access_context_manager_service_perimeter" "brain" {
  count  = var.enable_vpc_sc ? 1 : 0
  parent = "accessPolicies/${google_access_context_manager_access_policy.perimeter_policy[0].name}"
  name   = "accessPolicies/${google_access_context_manager_access_policy.perimeter_policy[0].name}/servicePerimeters/${var.name_prefix}_perimeter"
  title  = "${var.name_prefix}-perimeter"

  status {
    resources = ["projects/${data.google_project.this[0].number}"]
    # Confine the data-boundary services so exfiltration across the perimeter is blocked.
    restricted_services = [
      "storage.googleapis.com",
      "aiplatform.googleapis.com",
      "run.googleapis.com",
    ]
    vpc_accessible_services {
      enable_restriction = true
      allowed_services   = ["RESTRICTED-SERVICES"]
    }
  }
}

# Workforce Identity Federation: the bank's IdP groups federate in, so the same
# OIDC + IAM primitive as personal governs access with no per-user accounts.
resource "google_iam_workforce_pool" "bank" {
  count             = var.enable_workforce_identity ? 1 : 0
  parent            = "organizations/${var.org_id}"
  location          = "global"
  workforce_pool_id = "${var.name_prefix}-bank-pool"
  display_name      = "${var.name_prefix} bank workforce pool"
  description       = "Federates the bank IdP for controlled-profile access."
}

resource "google_iam_workforce_pool_provider" "bank_oidc" {
  count             = var.enable_workforce_identity ? 1 : 0
  workforce_pool_id = google_iam_workforce_pool.bank[0].workforce_pool_id
  location          = "global"
  provider_id       = "${var.name_prefix}-bank-oidc"
  display_name      = "Bank IdP (OIDC)"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "google.groups"        = "assertion.groups"
    "attribute.department" = "assertion.department"
  }

  oidc {
    issuer_uri = var.workforce_pool_issuer_uri
    client_id  = "${var.name_prefix}-brain"
  }
}
