# A Cloud Run v2 Job for batch work (index build, ingestion). Runs on demand, so
# there is no idle cost; it uses its own least-privilege service account.
resource "google_cloud_run_v2_job" "this" {
  name     = var.name
  project  = var.project_id
  location = var.location
  labels   = var.labels

  deletion_protection = false

  template {
    template {
      service_account = var.service_account

      containers {
        image = var.image
        args  = var.args

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
            memory = "1Gi"
          }
        }
      }
    }
  }
}
