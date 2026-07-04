# Module wiring. The profile shapes two things: whether services take internal-only
# ingress, and whether the controlled-only resources in controlled.tf are created.
locals {
  is_controlled = var.profile == "controlled"

  # Controlled locks ingress to internal (reachable only from within the perimeter);
  # personal allows all ingress but is still IAM-gated (never allUsers).
  service_ingress = local.is_controlled ? "INGRESS_TRAFFIC_INTERNAL_ONLY" : "INGRESS_TRAFFIC_ALL"

  # Export spans to in-tenancy Cloud Trace when observability is on, else no-op.
  otel_exporter = var.enable_observability ? "gcp" : "none"

  # Env every workload shares so the Vertex/genai clients bill and region correctly.
  common_env = {
    GOOGLE_CLOUD_PROJECT  = var.project_id
    GOOGLE_CLOUD_LOCATION = var.region
  }

  # The brain loads its policy from the bucket, so `brain grant` (which updates this
  # object) takes effect without a rebuild.
  policy_uri = "gs://${module.storage.index_bucket}/policy.yaml"
}

# The active policy, published to the bucket the brain reads it from.
resource "google_storage_bucket_object" "policy" {
  name   = "policy.yaml"
  bucket = module.storage.index_bucket
  source = "${path.module}/../config/${var.profile}.policy.yaml"
}

module "vertex" {
  source     = "./modules/vertex"
  project_id = var.project_id
}

module "observability" {
  source     = "./modules/observability"
  project_id = var.project_id
  enabled    = var.enable_observability
}

module "storage" {
  source        = "./modules/storage"
  project_id    = var.project_id
  location      = var.region
  name_prefix   = var.name_prefix
  labels        = var.labels
  force_destroy = var.force_destroy_buckets

  depends_on = [google_project_service.base]
}

module "registry" {
  source      = "./modules/registry"
  project_id  = var.project_id
  location    = var.region
  name_prefix = var.name_prefix
  labels      = var.labels

  depends_on = [google_project_service.base]
}

module "iam" {
  source        = "./modules/iam"
  project_id    = var.project_id
  name_prefix   = var.name_prefix
  index_bucket  = module.storage.index_bucket
  corpus_bucket = module.storage.corpus_bucket

  depends_on = [google_project_service.base]
}

# The three Cloud Run services (brain, agent, ui). Each runs as its own
# least-privilege service account and is invokable only by the invoker members.
module "brain_service" {
  source          = "./modules/run_service"
  project_id      = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-brain"
  image           = var.image_brain
  service_account = module.iam.brain_sa_email
  ingress         = local.service_ingress
  # The agent and UI call the brain, so they invoke it too (still never allUsers).
  invoker_members = concat(var.invoker_members, [
    "serviceAccount:${module.iam.agent_sa_email}",
    "serviceAccount:${module.iam.ui_sa_email}",
  ])
  labels = var.labels
  env = merge(local.common_env, {
    BRAIN_PROFILE = var.profile
    BRAIN_INDEX   = "gs://${module.storage.index_bucket}/index.json"
    # In-tenancy Vertex on the whole data-boundary path.
    BRAIN_EMBEDDINGS  = "vertex"
    BRAIN_SYNTH       = "gemini"
    BRAIN_SYNTH_MODEL = var.agent_model
    # Google-signed OIDC verified against this service's own URL as the audience.
    BRAIN_AUTH          = "google"
    BRAIN_AUTH_AUDIENCE = var.brain_audience
    BRAIN_AUTH_ISSUER   = "https://accounts.google.com"
    # Policy from the bucket (grant rollout) and proposals staged to the corpus bucket.
    BRAIN_POLICY           = local.policy_uri
    BRAIN_PROPOSE_GATE     = "gcs"
    BRAIN_PROPOSALS_BUCKET = module.storage.corpus_bucket
    BRAIN_OTEL             = local.otel_exporter
  })

  depends_on = [google_project_service.base]
}

module "agent_service" {
  source          = "./modules/run_service"
  project_id      = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-agent"
  image           = var.image_agent
  service_account = module.iam.agent_sa_email
  ingress         = local.service_ingress
  invoker_members = var.invoker_members
  labels          = var.labels
  env = merge(local.common_env, {
    BRAIN_PROFILE     = var.profile
    BRAIN_AGENT_MODE  = "live"
    BRAIN_AGENT_MODEL = var.agent_model
    BRAIN_URL         = "${module.brain_service.uri}/mcp"
    # The agent mints an ID token for this audience to call the brain.
    BRAIN_AUDIENCE = module.brain_service.uri
    BRAIN_OTEL     = local.otel_exporter
  })

  depends_on = [google_project_service.base]
}

module "ui_service" {
  source          = "./modules/run_service"
  project_id      = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-ui"
  image           = var.image_ui
  service_account = module.iam.ui_sa_email
  ingress         = local.service_ingress
  invoker_members = var.invoker_members
  labels          = var.labels
  env             = { BRAIN_PROFILE = var.profile }

  depends_on = [google_project_service.base]
}

# The two Cloud Run Jobs (index build, ingestion), run on demand not on a schedule.
# The index job reads the corpus bucket and writes the index bucket, so the corpus
# and the (Vertex) embeddings never leave the tenancy.
module "indexer_job" {
  source          = "./modules/run_job"
  project_id      = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-indexer"
  image           = var.image_indexer
  service_account = module.iam.indexer_sa_email
  labels          = var.labels
  # The image has no ENTRYPOINT, so args is the full argv (python first).
  args = [
    "python", "-m", "brain_app.indexer.build",
    "--corpus", "gs://${module.storage.corpus_bucket}",
    "--out", "gs://${module.storage.index_bucket}/index.json",
  ]
  env = merge(local.common_env, { BRAIN_EMBEDDINGS = "vertex" })

  depends_on = [google_project_service.base]
}

module "ingest_job" {
  source          = "./modules/run_job"
  project_id      = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-ingest"
  image           = var.image_ingest
  service_account = module.iam.ingest_sa_email
  labels          = var.labels
  env             = merge(local.common_env, { BRAIN_EMBEDDINGS = "vertex" })

  depends_on = [google_project_service.base]
}
