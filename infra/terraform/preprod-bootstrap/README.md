# JewelAI preproduction bootstrap

This isolated root creates only the foundation required by `Deploy preprod` in the exact
`mmjewellai-preprod` project and `europe-west1` region:

- the private, versioned Terraform state and exact-plan bucket;
- the `jewelai-preprod` Docker repository;
- the `jewelai-preprod-github` Workload Identity pool and `github-oidc` provider;
- the keyless `jewelai-preprod-deployer` service account and explicit administrative roles.

The OIDC provider accepts only `mlevin09/mmjewelai` tokens from `refs/heads/jewelai-v2`. It does not
accept pull-request or fork refs. Firebase Editor permits Firebase project/Web application
management, while Identity Toolkit Editor permits Identity Platform configuration; the deployer
also receives IAM Role Admin solely to manage the stack's bounded project custom roles. It receives
neither primitive Owner nor Editor. The stack also
validates and outputs the deterministic Asset bucket name for the main preproduction stack without
creating that bucket.

Initialize with the local bootstrap state, review a saved plan, and apply that exact plan. Supply the
authenticated operator identity only through `TF_VAR_operator_members`; never commit it. The state
bucket grants those explicit operators and the deployer bucket-scoped `roles/storage.admin`, which
is required to refresh the authoritative bucket IAM policy on later bootstrap plans. No operator
receives a project-scoped storage grant. The state bucket output is the remote backend used by the
main preproduction platform:

```bash
terraform -chdir=infra/terraform/preprod-bootstrap init -backend=false
terraform -chdir=infra/terraform/preprod-bootstrap plan -out=preprod-bootstrap.tfplan
terraform -chdir=infra/terraform/preprod-bootstrap apply preprod-bootstrap.tfplan
```

The preferred state and Asset bucket names may use only the documented project-number suffix when
global bucket-name ownership requires a deterministic fallback. This bootstrap never creates the
Asset bucket and never applies the main preproduction platform.
