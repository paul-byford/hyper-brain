# Infrastructure policy-as-code

OPA/conftest policies that assert the security properties this design treats as
first-order, complementing checkov's broad CIS-style checks. They evaluate the
Terraform sources statically, so they run in CI with no cloud.

- `security.rego` (package `main`, per file): the brain is never public (no
  `allUsers`/`allAuthenticatedUsers` on any IAM member), buckets enforce uniform
  access and public-access-prevention, and no workload gets a broad primitive role
  (`roles/owner`/`roles/editor`).
- `controlled.rego` (package `controlled`, `--combine`): the controlled profile
  must author a VPC-SC service perimeter and Workforce Identity Federation, so the
  perimeter-present and federation-present guarantees are checked, not just
  asserted in prose.

Run:

```sh
conftest test $(find infra -name '*.tf') -p infra/policy/security.rego
conftest test $(find infra -name '*.tf') --combine --namespace controlled -p infra/policy/controlled.rego
```
