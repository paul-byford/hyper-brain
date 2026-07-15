# Module wiring. The profile shapes two things: whether services take internal-only
# ingress, and whether the controlled-only resources in controlled.tf are created.
locals {
  is_controlled = var.profile == "controlled"

  # Controlled locks ingress to internal (reachable only from within the perimeter);
  # personal allows all ingress but is still IAM-gated (never allUsers).
  service_ingress = local.is_controlled ? "INGRESS_TRAFFIC_INTERNAL_ONLY" : "INGRESS_TRAFFIC_ALL"

  # Export spans to in-tenancy Cloud Trace when observability is on, else no-op.
  otel_exporter = var.enable_observability ? "gcp" : "none"

  # The index Job's fully-qualified resource name, so the brain can run it (via the
  # Cloud Run Admin API) when it accepts a proposal server-side.
  indexer_job_id = "projects/${var.project_id}/locations/${var.region}/jobs/${var.name_prefix}-indexer"

  # Env every workload shares so the Vertex/genai clients bill and region correctly.
  common_env = {
    GOOGLE_CLOUD_PROJECT  = var.project_id
    GOOGLE_CLOUD_LOCATION = var.region
    # Route google-genai (the ADK agent's Gemini calls) to Vertex in-tenancy, not the
    # public Gemini Developer API. The brain's synthesiser sets vertexai=True in code,
    # but the ADK agent relies on this env, so without it the agent gets no model.
    GOOGLE_GENAI_USE_VERTEXAI = "true"
  }

  # The brain loads its policy from the bucket, so `brain grant` (which updates this
  # object) takes effect without a rebuild.
  policy_uri = "gs://${module.storage.index_bucket}/policy.yaml"

  # The ingest Job reads its sources config from the bucket (change without rebuild).
  sources_uri = "gs://${module.storage.index_bucket}/sources.yaml"
}

# The active policy, published to the bucket the brain reads it from. It is the
# profile's base file (tracked, @example.com only) plus any `extra_grants` supplied
# via gitignored tfvars, so real identities are granted declaratively without ever
# landing in the committed config. Generated as content (not the raw file) so the
# merge happens at apply time.
locals {
  base_policy = yamldecode(file("${path.module}/../config/${var.profile}.policy.yaml"))
  policy_document = {
    version = try(local.base_policy.version, 1)
    domains = local.base_policy.domains
    grants = concat(
      [for g in local.base_policy.grants : {
        principal = g.principal
        domains   = g.domains
        write     = try(g.write, false)
      }],
      [for g in var.extra_grants : {
        principal = g.principal
        domains   = g.domains
        write     = g.write
      }],
      # The deployed ADK agent reads the brain as its own service account, so grant
      # it read access to every domain. Declarative (Terraform knows the SA email),
      # so the agent works out of the box with no personal data in the config.
      [{
        principal = module.iam.agent_sa_email
        domains   = local.base_policy.domains
        write     = false
      }],
    )
  }
}

resource "google_storage_bucket_object" "policy" {
  name    = "policy.yaml"
  bucket  = module.storage.index_bucket
  content = yamlencode(local.policy_document)
}

# The ingestion sources config, published for the ingest Job.
resource "google_storage_bucket_object" "sources" {
  name   = "sources.yaml"
  bucket = module.storage.index_bucket
  source = "${path.module}/../config/sources.yaml"
}

module "vertex" {
  source     = "./modules/vertex"
  project_id = var.project_id
}

# In-tenancy OCR for scanned/image PDFs uploaded through the Studio. A Google-managed
# processor parses the bytes inside the tenancy; the brain reads its name from
# BRAIN_DOCAI_PROCESSOR and routes scanned PDFs to it (text PDFs still use pypdf).
resource "google_document_ai_processor" "ocr" {
  # checkov:skip=CKV2_GCP_22: CMEK on the OCR processor adds a KMS key's cost and
  # teardown complexity; the uploaded bytes are transient and never leave the tenancy.
  # A controlled deployment would supply kms_key_name here (as with the registry CMEK).
  project      = var.project_id
  location     = "eu"
  display_name = "${var.name_prefix}-ocr"
  type         = "OCR_PROCESSOR"
  depends_on   = [module.vertex]
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
  source                 = "./modules/iam"
  project_id             = var.project_id
  name_prefix            = var.name_prefix
  index_bucket           = module.storage.index_bucket
  corpus_bucket          = module.storage.corpus_bucket
  shares_bucket          = module.storage.shares_bucket
  model_armor_enabled    = var.model_armor_template != ""
  agent_registry_enabled = var.enable_agent_registry

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
  # The agent and UI call the brain, so they invoke it too. When the OAuth AS is
  # live, the brain also opens to allUsers on the personal profile so remote MCP
  # connectors can reach it -- the OAuth bearer is then the sole gate (controlled
  # stays perimeter-internal).
  invoker_members = concat(var.invoker_members, [
    "serviceAccount:${module.iam.agent_sa_email}",
    "serviceAccount:${module.iam.ui_sa_email}",
  ], local.oauth_live && !local.is_controlled ? ["allUsers"] : [])
  labels = var.labels
  env = merge(local.common_env, {
    BRAIN_PROFILE = var.profile
    BRAIN_INDEX   = "gs://${module.storage.index_bucket}/index.json"
    # Reload the index from the bucket after this many seconds, so a re-index
    # appears without a redeploy (0 = cache for the instance's life).
    BRAIN_INDEX_TTL = "300"
    # In-tenancy Vertex on the whole data-boundary path.
    BRAIN_EMBEDDINGS  = "vertex"
    BRAIN_SYNTH       = "gemini"
    BRAIN_SYNTH_MODEL = var.agent_model
    # Raw-to-wiki curation (the Studio "clean up with AI" toggle) runs an in-tenancy
    # Gemini pass; on-demand per draft, so it costs nothing unless a caller uses it.
    BRAIN_CURATE = "gemini"
    # In-tenancy OCR for scanned/image PDFs: when set, uploads route to Document AI
    # instead of the pypdf stub, which only reads text PDFs. The parser needs the
    # full resource path (the resource's .name attribute is only the short id).
    BRAIN_DOCAI_PROCESSOR = "projects/${var.project_id}/locations/eu/processors/${google_document_ai_processor.ocr.name}"
    # Google-signed OIDC verified against this service's own URL as the audience.
    BRAIN_AUTH_AUDIENCE = var.brain_audience
    BRAIN_AUTH_ISSUER   = "https://accounts.google.com"
    # Policy from the bucket (grant rollout) and proposals staged to the corpus bucket.
    BRAIN_POLICY       = local.policy_uri
    BRAIN_PROPOSE_GATE = "gcs"
    # (BRAIN_CODE_INTERPRETER is merged in below from local.code_interpreter_env.)
    BRAIN_PROPOSALS_BUCKET = module.storage.corpus_bucket
    # Personal notes (add_note) land live into the caller's personal domain in the
    # corpus bucket, so the next index build picks them up like any other content.
    BRAIN_CORPUS_BUCKET = module.storage.corpus_bucket
    # The dynamic sharing overlay: per-owner files in the dedicated shares bucket.
    BRAIN_SHARES_STORE  = "gcs"
    BRAIN_SHARES_BUCKET = module.storage.shares_bucket
    # Agent Studio's shared custom-specialist registry lives in the same shares bucket.
    BRAIN_AGENTS_STORE = "gcs"
    # Community moderation reports: a single object in the shares bucket.
    BRAIN_REPORTS_STORE  = "gcs"
    BRAIN_REPORTS_BUCKET = module.storage.shares_bucket
    # Server-side review: the brain promotes an accepted proposal in the corpus bucket
    # and runs this index Job to rebuild. Enforcement (who may accept) is in-app.
    BRAIN_INDEXER_JOB = local.indexer_job_id
    # Let the public browser UI call the brain's REST facade (empty = no CORS, the
    # agent/MCP path). Set to the UI's origin on the second apply.
    BRAIN_CORS_ORIGINS = var.ui_origin
    BRAIN_OTEL         = local.otel_exporter
    # When the OAuth AS is live, accept both Google ID tokens (the agent) and our
    # AS's access tokens (remote connectors); otherwise Google only.
    }, local.code_interpreter_env, local.memory_env, local.model_armor_env, local.oauth_live ? {
    BRAIN_AUTH         = "composite"
    BRAIN_OAUTH_ISSUER = var.auth_audience
    BRAIN_OAUTH_JWKS   = "${var.auth_audience}/jwks"
    } : {
    BRAIN_AUTH = "google"
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
  }, local.code_interpreter_env, local.memory_env)

  depends_on = [google_project_service.base]
}

# Optional managed sandbox for the analyst: the Vertex AI Code Interpreter extension. Off by
# default -- the analyst then runs its Python in Gemini's in-region built-in sandbox. When
# enabled, the extension's resource name flows to the brain + agent as BRAIN_CODE_INTERPRETER
# and the analyst uses the managed, stateful sandbox instead. NOTE: the Code Interpreter is
# us-central1-only, so enabling this takes code execution CROSS-REGION from europe-west2.
module "code_interpreter" {
  source     = "./modules/code_interpreter"
  count      = var.enable_code_interpreter ? 1 : 0
  project_id = var.project_id
  location   = var.code_interpreter_location
}

locals {
  code_interpreter_env = var.enable_code_interpreter ? {
    BRAIN_CODE_INTERPRETER = module.code_interpreter[0].resource_name
  } : {}
}

locals {
  # User-scoped memory (Agent Engine Sessions + Memory Bank) is on when agent_engine_resource
  # names a provisioned instance. Create it once with scripts/provision_agent_engine.py
  # (europe-west2, in-region) and record its resource name in the gitignored tfvars -- it is
  # a project-specific value, so it never lands in a tracked file. Its name flows to the
  # brain + agent as BRAIN_AGENT_ENGINE, and the team gains persistent conversations and
  # per-user memory. There is no apply-time script (that would need the vertex SDK on the
  # apply host); Terraform just wires the env from the variable.
  memory_env = var.agent_engine_resource != "" ? {
    BRAIN_AGENT_ENGINE = var.agent_engine_resource
  } : {}

  # Model Armor content guard is on when model_armor_template names a template. Create it once
  # with scripts/provision_model_armor.py (in a region that supports it, e.g. europe-west2) and
  # record the resource name in the gitignored tfvars. Its name flows to the brain as
  # BRAIN_MODEL_ARMOR_TEMPLATE; the brain SA is also granted roles/modelarmor.user below.
  model_armor_env = var.model_armor_template != "" ? {
    BRAIN_MODEL_ARMOR_TEMPLATE = var.model_armor_template
  } : {}
}

module "ui_service" {
  source          = "./modules/run_service"
  project_id      = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-ui"
  image           = var.image_ui
  service_account = module.iam.ui_sa_email
  ingress         = local.service_ingress
  # On the personal profile the UI is public: it serves a landing page to anyone, and
  # the app behind it is gated by Google sign-in (its data calls hit the brain, which
  # enforces auth). Controlled stays perimeter-internal.
  invoker_members = concat(var.invoker_members, !local.is_controlled ? ["allUsers"] : [])
  labels          = var.labels
  # The SPA's live config (api/auth/mcp URLs) is injected here and served at runtime by
  # ui/serve.py, so the deployed demo-vs-live mode is declarative and never depends on what
  # data/config.json happened to be baked into the image. auth_url only appears once the AS
  # is live (second apply), which is exactly when browser sign-in should switch on.
  env = merge({
    BRAIN_PROFILE    = var.profile
    BRAIN_UI_API_URL = module.brain_service.uri
    BRAIN_UI_MCP_URL = "${module.brain_service.uri}/mcp"
    }, local.oauth_live ? {
    BRAIN_UI_AUTH_URL = var.auth_audience
  } : {})

  depends_on = [google_project_service.base]
}

# The brain runs the index Job when it accepts a proposal server-side, so its service
# account needs run.invoker on that Job (scoped to the one Job, nothing broader).
resource "google_cloud_run_v2_job_iam_member" "brain_runs_indexer" {
  project  = var.project_id
  location = var.region
  name     = module.indexer_job.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${module.iam.brain_sa_email}"
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
  # Pull configured sources (web/git for in-tenancy fetch) and land provenance-
  # stamped markdown straight into the corpus bucket.
  args = [
    "python", "-m", "brain_app.ingest.run",
    "--sources", local.sources_uri,
    "--corpus", "gs://${module.storage.corpus_bucket}",
  ]
  env = merge(local.common_env, { BRAIN_EMBEDDINGS = "vertex" })

  depends_on = [google_project_service.base]
}
