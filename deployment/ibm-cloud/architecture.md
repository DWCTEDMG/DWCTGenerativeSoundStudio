# Architecture

Windows Studio connects through an SSH tunnel to a customer-owned IBM VPC virtual server. Only TCP 22 from the administrator's /32 is permitted inbound. The existing FastAPI container is published on host loopback port 7863 and requires its existing bearer token authentication. SSH encrypts network traffic; Nginx terminates TLS on loopback 8443 using a server-generated certificate trusted explicitly by the customer client. The SSH tunnel forwards to 8443.

The default bx2-2x8 CPU instance runs Ubuntu 24.04 amd64 and Docker. `/srv/edmg` on the boot disk persists application data across container restarts. Instance replacement and destroy delete this storage. Backups are customer-operated. Optional COS, separate storage, GPU, managed monitoring, high availability and private registry authentication are not implemented. No GPU inference claims are made.

Tokens are generated on the server, stored in a root-only environment file, and never passed through Terraform state. Docker logs rotate. External AI uses the application's existing provider configuration. No publisher backend is required.
