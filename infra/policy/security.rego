# Project-specific infrastructure policy (OPA/conftest), complementing checkov's
# broad CIS-style checks. These assert the properties this design treats as
# first-order: the brain is never public, buckets are locked down, and no workload
# gets a broad primitive role. Evaluated per file over the Terraform sources, so it
# runs in CI with no cloud.
package main

import rego.v1

_public := {"allUsers", "allAuthenticatedUsers"}

# Every IAM member string declared on an *_iam_member resource in this file.
iam_members contains member if {
	some kind, blocks in input.resource
	contains(kind, "iam_member")
	some _, body in blocks
	member := body.member
}

# ...and every member of an *_iam_binding resource.
iam_members contains member if {
	some kind, blocks in input.resource
	contains(kind, "iam_binding")
	some _, body in blocks
	some member in body.members
}

# The brain must never be public (section 7): no allUsers / allAuthenticatedUsers.
deny contains msg if {
	some member in iam_members
	member in _public
	msg := sprintf("IAM member %q would make a resource public; the brain must never be public", [member])
}

# Buckets must enforce uniform bucket-level access.
deny contains msg if {
	some name, body in input.resource.google_storage_bucket
	not body.uniform_bucket_level_access == true
	msg := sprintf("google_storage_bucket.%s must set uniform_bucket_level_access = true", [name])
}

# Buckets must enforce public access prevention.
deny contains msg if {
	some name, body in input.resource.google_storage_bucket
	not body.public_access_prevention == "enforced"
	msg := sprintf("google_storage_bucket.%s must set public_access_prevention = \"enforced\"", [name])
}

# No workload may be granted a broad primitive role (least privilege).
deny contains msg if {
	some kind, blocks in input.resource
	contains(kind, "iam_member")
	some name, body in blocks
	body.role in {"roles/owner", "roles/editor"}
	msg := sprintf("%s.%s grants the broad role %s; use a least-privilege role instead", [kind, name, body.role])
}
