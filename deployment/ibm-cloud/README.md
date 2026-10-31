# EDMG Studio IBM Cloud candidate 1.0.0

Publisher: Driftwoodcraftthing / DWCT Productions. Store product: 9NKHCN1H1B13.

This candidate provisions a VPC, subnet, restricted security group, virtual server and floating IP. The default profile is CPU; optional CUDA and NVIDIA vGPU modes are configured with `accelerator_profile`. It runs the existing Python 3.12 Studio backend on 7863, with persistent boot-disk storage and authentication. See architecture.md for security and qualification limits. This is not yet a qualified GPU Catalog release.

## Prerequisites

Install Terraform >=1.9,<2, IBM CLI, SSH and Docker with a Linux daemon. Supply `IC_API_KEY` privately through the environment. Never commit credentials, state or tfvars. Use encrypted, access-controlled remote state with locking for team deployments.

Provide an existing resource group, regional SSH key and Ubuntu 24.04 amd64 VPC image ID. Verify image, profile and zone availability with `ibmcloud is images`, `ibmcloud is instance-profiles`, and `ibmcloud is zones`. A100 profiles are select availability in `us-east`; visible profiles do not guarantee service entitlement, quota or capacity. The single-GPU profile is `gx3d-24x120x1a100p` with 80 GB GPU memory. Use a separate Schematics workspace and state for the GPU region; do not change the region of the running Dallas workspace. The deployer needs resource-group Viewer and VPC Infrastructure Services Editor scoped to the target group, with lookup access to the existing image/key. Verify least-privilege permissions against customer account policies. Catalog management permissions are separate. The application receives no IBM API key.

## Build and deploy

From repository root, build the CPU backend using its existing lockfile:

```sh
docker build --build-arg EDMG_TORCH_EXTRA=cpu -t YOUR_REGISTRY/edmg-backend:ibm-1.0.0 -f studio/edmg-studio/python_backend/Dockerfile studio/edmg-studio/python_backend
docker push YOUR_REGISTRY/edmg-backend:ibm-1.0.0
cd deployment/ibm-cloud
```

Inspect the Docker context for secrets before building. Use a public customer image pinned by sha256 digest; private-registry authentication is not included. Copy terraform.tfvars.example to terraform.tfvars and replace every placeholder. Region and zone must agree. `profile` selects compute; `boot_capacity` selects storage; prefix/environment name resources. Restrict admin_cidr to your public IPv4 /32.

```sh
terraform init
terraform fmt -check -recursive
terraform validate
terraform plan -out=reviewed.tfplan
terraform apply reviewed.tfplan
terraform output ssh_tunnel
```

Apply creates billable resources. No apply was run during development. Budget VSI uptime, boot storage, floating IP, bandwidth, registry and external inference charges using IBM's current estimator. No paid load balancer or managed logging service is created.

### NVIDIA GPU image and activation

For CUDA, build with `--build-arg EDMG_TORCH_EXTRA=cuda`, publish as a separate immutable image, and set `backend_image` to its `@sha256:` digest. The `ibm-cloud.yml` manual workflow builds and publishes `v1-cuda`; use the digest printed in the workflow summary. For an A100 deployment, set `region = us-east`, `zone = us-east-1`, `profile = gx3d-24x120x1a100p`, and `accelerator_profile = nvidia-vgpu` in a new workspace. Do not apply these values to the Dallas workspace.

`nvidia-vgpu` mode installs NVIDIA Container Toolkit but intentionally does not install a generic NVIDIA driver. Obtain the licensed Linux vGPU guest driver and client configuration token from the NVIDIA Licensing Portal/CLS under the account's entitlement. For the Ubuntu VM, install the `.deb` guest driver with `sudo apt-get install ./nvidia-linux-grid-580_580.178.04_amd64.deb` after transferring it over verified SSH. Reboot, then place the token at `/etc/nvidia/ClientConfigToken/client_configuration_token.tok` with root-only permissions. Set `/etc/nvidia/gridd.conf` `FeatureType=2` for RTX Virtual Workstation on a physical GPU. Keep driver packages and token out of Git, the container image, Terraform variables/state, and chat. The backend service is gated on both the NVIDIA driver (`nvidia-smi -L`) and token file, so it will restart until licensing setup is complete. After setup run `sudo systemctl restart edmg`, check `nvidia-smi`, then verify `torch.cuda.is_available()` inside the backend container. NVIDIA describes IBM Cloud vGPU as BYOL; the customer must supply the vGPU license and client configuration. See https://docs.nvidia.com/vgpu/faq/latest/nls.html and https://docs.nvidia.com/vgpu/latest/grid-licensing-user-guide/configuring-nls-licensed-client.html.

## Windows connectivity and verification

Verify the SSH host fingerprint through the IBM console. Run the emitted tunnel command, adding `-i` for your private key if needed. In WinUI Settings choose external backend, URL `https://127.0.0.1:17863`. Securely retrieve the token from `/etc/edmg/backend.env` over SSH and save it in the native backend token setting (Windows Credential Locker). Keep it out of command history and logs.

Check `/health` through the tunnel, then verify a protected endpoint rejects an unauthenticated request and accepts your token. Test project creation, upload, planning and desktop reconnection. A health response alone does not qualify inference. Nginx terminates TLS on loopback 8443 behind the SSH tunnel. Securely copy /etc/edmg/tls.crt over verified SSH, verify its fingerprint, and trust this customer-specific certificate in the Windows Current User trusted root store before connecting. Never disable certificate validation. The self-signed certificate expires after 365 days; renew it before expiry and replace client trust after verifying the new fingerprint. Production operators may replace it with their own CA-issued certificate for localhost/127.0.0.1. TLS and Windows trust behavior require live qualification.

## Capabilities and operations

The frozen backend CPU/core/audio/ASR/internal-video/AWS dependency profile is reused unchanged. CPU mode is explicit and rule-based planning is the default. GPU video generation is unavailable in this variation. For an external Studio-compatible AI service, set `EDMG_AI_MODE=http` and `EDMG_AI_BASE_URL` in the root-only environment file and restart edmg. This is the Studio AI API contract, not an arbitrary OpenAI URL. Provider-specific settings are also supported by the existing backend. External inference remains untested.

Use `systemctl status edmg`, `journalctl -u edmg`, `docker logs edmg`, and `/var/log/cloud-init-output.log` for troubleshooting. Check image access, DNS/HTTPS egress, disk and memory. Initial cloud-init can race floating-IP association; package installation retries up to 60 times. If retries are exhausted, inspect connectivity before retrying failed bootstrap steps without regenerating the token.

Back up `/srv/edmg` with jobs stopped and verify restoration before upgrades. Build and test an immutable replacement image; inspect the plan for VSI replacement before changing user_data. Restore data before accepting a replacement. Retain the prior digest for rollback. No automatic backup or managed alerts are included.

For cleanup, export and verify data first, review `terraform plan -destroy`, then run `terraform destroy`. Instance storage is deleted. Existing resource group, SSH key, image registry and external model accounts remain customer-owned.

## Release and Catalog onboarding

Run Terraform fmt/init/validate, manifest checks and container smoke tests. IBM manifest schema validation and a real private-catalog deployment are still required. JSON parsing alone is not schema validation. No tag should be created until available checks pass and the runtime is qualified.

Package the repository-root ibm_catalog.json with deployment/ibm-cloud under a single archive root. Terraform working directory is `deployment/ibm-cloud`; the root manifest is authoritative and the local copy must match. Recommended variation: **EDMG Studio Backend - Standard**. Recommended version: **1.0.0**.

After qualification and release approval, create/push `ibm-v1.0.0`, download its archive, inspect its structure and repeat validation from the extracted working directory. Intended URL, not yet submission-ready:
`https://github.com/DWCTEDMG/DWCTGenerativeSoundStudio/archive/refs/tags/ibm-v1.0.0.tar.gz`

1. Create/select an IBM private catalog.
2. Import a Terraform deployable architecture from the verified tag archive.
3. Select the standard variation and deployment/ibm-cloud working directory.
4. Review imported inputs, IAM permissions, documentation and customer credentials.
5. Run IBM validation in a customer test account; perform API and desktop acceptance tests.
6. Review support/licensing metadata and costs; make no unverified compliance claims.
7. Destroy validation resources and request publication review only after approval.

References: https://cloud.ibm.com/docs/secure-enterprise?topic=secure-enterprise-create-da and https://cloud.ibm.com/docs/secure-enterprise?topic=secure-enterprise-onboard-da
