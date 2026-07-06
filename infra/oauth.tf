# The in-tenancy OAuth 2.1 Authorization Server that lets remote MCP connectors
# (Claude/ChatGPT custom connectors) register and sign in via Google. It runs from
# the same image as the brain (different entrypoint) and is stateless, so it stays
# scale-to-zero with no datastore -- only its RSA signing key is durable.
#
# Bring-up is inherently two-step because the upstream Google OAuth client needs
# this service's callback URL, which isn't known until it exists:
#   1. `brain up`  -> creates the service (placeholder), prints its auth_url.
#   2. In the Google console, create an OAuth client with redirect
#      <auth_url>/oauth2/callback; put its id/secret in config/<profile>.tfvars.
#   3. `brain up`  -> the AS goes live and the brain opens to remote connectors.

locals {
  oauth_enabled = var.enable_oauth
  # After the first apply the real image is set; only then run the AS entrypoint.
  image_ready = var.image_brain != "gcr.io/cloudrun/hello"
  # The upstream Google client id/secret have been supplied (step 2 above). The
  # client secret is a sensitive variable, but whether it is *set* is not a secret;
  # nonsensitive() keeps this boolean usable in for_each (invoker_members) without
  # exposing the value itself.
  google_creds_set = nonsensitive(var.google_client_id != "" && var.google_client_secret != "")
  # The AS is actually serving (real image + Google client configured + URL known).
  oauth_live = local.oauth_enabled && local.image_ready && local.google_creds_set && var.auth_audience != ""
}

# --- Signing key: generated in your tenancy, stored in Secret Manager ---
resource "tls_private_key" "oauth_signing" {
  count     = local.oauth_enabled ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "google_secret_manager_secret" "oauth_signing_key" {
  count     = local.oauth_enabled ? 1 : 0
  secret_id = "${var.name_prefix}-oauth-signing-key"
  labels    = var.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.base]
}

resource "google_secret_manager_secret_version" "oauth_signing_key" {
  count       = local.oauth_enabled ? 1 : 0
  secret      = google_secret_manager_secret.oauth_signing_key[0].id
  secret_data = tls_private_key.oauth_signing[0].private_key_pem
}

# --- Upstream Google OAuth client (id/secret from gitignored tfvars) ---
resource "google_secret_manager_secret" "google_client_id" {
  count     = local.oauth_enabled ? 1 : 0
  secret_id = "${var.name_prefix}-google-client-id"
  labels    = var.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.base]
}

resource "google_secret_manager_secret_version" "google_client_id" {
  count       = local.oauth_enabled && local.google_creds_set ? 1 : 0
  secret      = google_secret_manager_secret.google_client_id[0].id
  secret_data = var.google_client_id
}

resource "google_secret_manager_secret" "google_client_secret" {
  count     = local.oauth_enabled ? 1 : 0
  secret_id = "${var.name_prefix}-google-client-secret"
  labels    = var.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.base]
}

resource "google_secret_manager_secret_version" "google_client_secret" {
  count       = local.oauth_enabled && local.google_creds_set ? 1 : 0
  secret      = google_secret_manager_secret.google_client_secret[0].id
  secret_data = var.google_client_secret
}

# --- The AS's own least-privilege service account + read access to its secrets ---
resource "google_service_account" "oauth" {
  count        = local.oauth_enabled ? 1 : 0
  account_id   = "${var.name_prefix}-oauth"
  display_name = "Hyper Brain OAuth Authorization Server"
  project      = var.project_id
}

resource "google_secret_manager_secret_iam_member" "oauth_secret_access" {
  for_each = local.oauth_enabled ? toset([
    google_secret_manager_secret.oauth_signing_key[0].secret_id,
    google_secret_manager_secret.google_client_id[0].secret_id,
    google_secret_manager_secret.google_client_secret[0].secret_id,
  ]) : toset([])
  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.oauth[0].email}"
}

# --- The AS service. Public ingress + allUsers: the OAuth endpoints must be
#     reachable by the connector and the user's browser; OAuth is the gate. The
#     entrypoint + secrets wire in only once the image and Google client exist, so
#     the first apply is a clean placeholder. ---
module "auth_service" {
  count           = local.oauth_enabled ? 1 : 0
  source          = "./modules/run_service"
  project_id      = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-auth"
  image           = var.image_brain
  service_account = google_service_account.oauth[0].email
  ingress         = "INGRESS_TRAFFIC_ALL"
  invoker_members = ["allUsers"]
  labels          = var.labels
  args            = local.oauth_live ? ["python", "-m", "brain_app.oauth.run"] : []
  env = merge(local.common_env, {
    OAUTH_ISSUER   = var.auth_audience  # this service's own URL
    OAUTH_RESOURCE = var.brain_audience # the brain URL (access-token audience)
  })
  secret_env = local.oauth_live ? {
    OAUTH_SIGNING_KEY    = google_secret_manager_secret.oauth_signing_key[0].secret_id
    GOOGLE_CLIENT_ID     = google_secret_manager_secret.google_client_id[0].secret_id
    GOOGLE_CLIENT_SECRET = google_secret_manager_secret.google_client_secret[0].secret_id
  } : {}
  depends_on = [
    google_project_service.base,
    google_secret_manager_secret_version.oauth_signing_key,
    google_secret_manager_secret_version.google_client_id,
    google_secret_manager_secret_version.google_client_secret,
  ]
}
