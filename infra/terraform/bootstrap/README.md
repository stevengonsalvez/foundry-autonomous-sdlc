# Bootstrap: remote state storage

Separate root config with **local** state (this folder's `terraform.tfstate`,
git-ignored). It creates what the stack's `azurerm` backend needs:

| Resource | Settings |
|---|---|
| `rg-<prefix>-tfstate` | resource group, separate from the stack RG |
| `st<prefix>tf<suffix>` | StorageV2 LRS, shared keys off (Entra ID only), TLS 1.2, HTTPS only, infrastructure encryption, no public blobs, firewall default Deny + your IP, blob versioning, 30-day blob and container soft delete |
| container `tfstate` | private |
| role assignment | Storage Blob Data Contributor for the principal running Terraform, container scope |

## Steps

Run from `infra/terraform/bootstrap`, logged in with `az login` to the trial
subscription.

1. Write `bootstrap.tfvars` (git-ignored by `*.tfvars`):

   ```bash
   cat > bootstrap.tfvars <<EOF
   subscription_id   = "<subscription-id>"
   allowed_ip_ranges = ["$(curl -4 -s https://ifconfig.me)"]
   EOF
   ```

2. Create the storage:

   ```bash
   terraform init
   terraform plan -var-file=bootstrap.tfvars -out bootstrap.tfplan
   terraform apply bootstrap.tfplan
   ```

3. Record the module moves in the LOCAL state first (from `infra/terraform`).
   A plan does not save `moved` blocks; only an apply does. Expect
   `0 to add, 0 to change, 0 to destroy`:

   ```bash
   cd ..
   terraform apply
   ```

4. Migrate the state to the bucket:

   ```bash
   cp backend.tf.example backend.tf
   terraform -chdir=bootstrap output -raw backend_hcl > backend.hcl
   terraform init -migrate-state -backend-config=backend.hcl
   terraform plan    # expect: 0 to add, 0 to change, 0 to destroy
   ```

   `AuthorizationFailure` (403) means the firewall: your IPv4 egress is not in
   `allowed_ip_ranges`. `AuthorizationPermissionMismatch` means the role
   assignment has not propagated yet: wait a few minutes and retry.

5. Once the plan is clean, delete the stack's local `terraform.tfstate` and
   `terraform.tfstate.backup` (the remote copy is now the source of truth).
   Commit `backend.tf` (no secrets) so every clone uses the remote state;
   `backend.hcl` stays git-ignored, copy it from `backend.hcl.example`.

## Notes

- Egress IP changed? Update `allowed_ip_ranges` and re-apply bootstrap, or
  the backend returns 403.
- Keep this folder's `terraform.tfstate`. Without it, tear down with
  `az group delete -n rg-fsdlc-tfstate` instead of `terraform destroy`.
- Destroy only after the stack is destroyed:
  `terraform destroy -var-file=bootstrap.tfvars`. Then remove the stack's
  `backend.tf` and `backend.hcl`, which point at the deleted account.
