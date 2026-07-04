# A Cloud Run v2 service: scale-to-zero, its own service account, and invokable only
# by the granted members (never allUsers). Ingress is caller-controlled so the
# controlled profile can lock it to internal-only.

resource "google_cloud_run_v2_service" "this" {
  name     = var.name
  project  = var.project_id
  location = var.location
  ingress  = var.ingress
  labels   = var.labels

  # Disposable by design (scale-to-zero demo); teardown must not be blocked.
  deletion_protection = false

  template {
    service_account = var.service_account

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }
}

# Edge authorisation (section 7): only these members may invoke the service.
resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = toset(var.invoker_members)

  name     = google_cloud_run_v2_service.this.name
  project  = var.project_id
  location = var.location
  role     = "roles/run.invoker"
  member   = each.value
}
