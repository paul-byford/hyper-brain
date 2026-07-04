output "corpus_bucket" {
  value = google_storage_bucket.corpus.name
}

output "index_bucket" {
  value = google_storage_bucket.index.name
}
