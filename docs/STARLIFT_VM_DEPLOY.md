# EDMG Studio on a Spaceship / Starlift VM

This repo is desktop-first, but it can also run as a browser-served Studio
control plane on an Ubuntu VM.

This deployment path is intended for:

- Ubuntu 24.04 VMs
- Docker-based installs
- browser access over one HTTP port
- optional host-level Ollama or ComfyUI sidecars

Important limits:

- Electron-only features do not exist in the browser build
- no native folder picker
- no native file reveal/open actions
- no desktop restart hooks
- CPU-only VMs are not a good fit for heavy local diffusion renders
- the safest default for server startup is `rule_based` planning unless you
  explicitly wire Ollama or a remote AI path

## Files added for this path

- `studio/edmg-studio/Dockerfile.starlift`
- `studio/edmg-studio/deployment/starlift/nginx.conf`
- `docker-compose.starlift.yml`

The deployment runs two long-lived containers:

- `web`
  - nginx serving the built React app on port `8080`
  - reverse proxy for `/v1/*`, `/health`, `/docs`, `/redoc`, and `/openapi.json`
- `backend`
  - the existing FastAPI container on internal port `7863`

Compose also runs a short-lived `data-init` job before the backend. It assigns
the bind-mounted runtime directories to the backend's non-root UID/GID
`10001:10001`, then exits. The ownership migration is recursive only when a
directory's top-level ownership is different, so later starts remain fast.

Default port:

- `8080`

## VM bootstrap

1. Add your public SSH key in Spaceship.
2. Connect with the Spaceship SSH port:

```bash
ssh -p 22022 <user>@<vm-ip>
```

3. Clone the repo onto the VM.
4. Install Docker Engine and the Docker Compose plugin.

## Run EDMG Studio

From the repo root:

```bash
docker compose -f docker-compose.starlift.yml up -d --build
```

Then open:

```text
http://<vm-ip>:8080
```

## Optional host-side services

The compose file maps `host.docker.internal` to the VM host gateway for the
backend container, so it can talk to services running directly on the VM.

Examples:

- host Ollama: `http://host.docker.internal:11434`
- host ComfyUI: `http://host.docker.internal:8188`

Override them at launch time if needed:

```bash
EDMG_AI_PROVIDER=ollama \
EDMG_AI_OLLAMA_URL=http://host.docker.internal:11434 \
EDMG_COMFYUI_URL=http://host.docker.internal:8188 \
docker compose -f docker-compose.starlift.yml up -d --build
```

## Recommended server defaults

For a plain 8 vCPU / 16 GiB CPU VM:

- start with `EDMG_AI_PROVIDER=rule_based`
- add Ollama only if you actually need local planning on the VM
- treat ComfyUI as optional and preferably remote/GPU-backed
- keep the built-in backend bundle for project management, exports, queueing,
  FFmpeg assembly, and the Studio UI

## Data layout

Persistent runtime data is stored under:

- `./starlift-data/data`
- `./starlift-data/models`
- `./starlift-data/cache`
- `./starlift-data/logs`
- `./starlift-data/external`

These host directories are owned by UID/GID `10001:10001` so the hardened
non-root backend can write to them. Do not change their ownership while the
containers are running.

## Logs and health

Check status:

```bash
docker compose -f docker-compose.starlift.yml ps
```

Tail logs:

```bash
docker compose -f docker-compose.starlift.yml logs -f edmg-studio-web edmg-studio-backend
```

Probe health:

```bash
curl http://127.0.0.1:8080/health
```
