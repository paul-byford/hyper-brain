# Controlled-profile assertions, evaluated in --combine mode so they can reason
# across all Terraform files at once (existence checks). Run with:
#   conftest test infra --combine --namespace controlled -p infra/policy
package controlled

import rego.v1

# True if any file authors a VPC-SC service perimeter.
perimeter_defined if {
	some file in input
	file.contents.resource.google_access_context_manager_service_perimeter
}

# True if any file authors a Workforce Identity pool.
workforce_pool_defined if {
	some file in input
	file.contents.resource.google_iam_workforce_pool
}

# The controlled profile's isolation rests on the perimeter and federation being
# authored in the modules (even though they are toggled off for the personal demo).
deny contains msg if {
	not perimeter_defined
	msg := "controlled profile must author a VPC-SC service perimeter (google_access_context_manager_service_perimeter)"
}

deny contains msg if {
	not workforce_pool_defined
	msg := "controlled profile must author Workforce Identity Federation (google_iam_workforce_pool)"
}
