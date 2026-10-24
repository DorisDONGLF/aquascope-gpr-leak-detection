# Deploy the complete application

GitHub stores the source and trained weights. A Python/Docker host runs detection,
review persistence and exports. The application is served from one HTTPS origin;
no browser-to-localhost connection or GitHub Pages Python backend is required.

## Suggested pilot: Hugging Face Docker Space

At the time of preparation (2026-10-24), creating Docker/Gradio compute Spaces
requires a paid plan. HF PRO is listed at USD 9/month. CPU Basic is listed as
2 vCPU / 16 GB RAM with no additional hourly hardware charge. Confirm current
terms and prices in the account before subscribing:

- https://huggingface.co/pricing
- https://huggingface.co/docs/hub/spaces-overview
- https://huggingface.co/docs/hub/en/spaces-sdks-docker

1. Create the hosting account and choose its subscription yourself.
2. Create a **public Docker Space**, using **CPU Basic**, with port **7860**.
3. Copy this repository's files, including the two model directories, into the Space.
4. Add this YAML header above the Space README:

```yaml
---
title: AquaScope GPR Leak Detection
emoji: 🌊
colorFrom: pink
colorTo: gray
sdk: docker
app_port: 7860
---
```

5. Wait for the build and check `/health` on the deployed app domain.
6. Upload one SGY, confirm candidates and images, save a review, refresh, and
   export CSV/DXF/SHP before sharing the final app URL.

## Files and review persistence

Mount a persistent writable directory at `/data` (or set `APP_DATA_DIR`). The
server writes uploads and runs beneath it. Without persistent storage, container
replacement/rebuilds can erase uploads and reviews. Export results before any
restart if running a temporary pilot. A live-memory `LOCK` and one inference
queue assume a **single container instance**; do not enable replicas without
moving jobs and review writes to a shared database/queue.

Each browser gets an HttpOnly workspace cookie. Its uploads, run list, images,
reviews and exports are isolated from other browsers. Clearing the cookie loses
access to that workspace. Anyone can open the app and create their own workspace;
this version does not provide multi-expert accounts or cross-browser shared runs.

The default public upload limit is 512 MB per file, configurable through
`MAX_UPLOAD_BYTES`. Model inference is queued and uses the unchanged weights.
For sustained public traffic, add managed ingress rate/storage limits and a
retention policy in the hosting platform. Do not expose the local-only
`server/app.py` entry point directly to the internet: use `public_server.py`.

## Other Docker hosts

Use the included Dockerfile. Configure the platform's public HTTPS domain,
container port 7860 (or its supplied `PORT`), and a persistent volume. The optional
`PUBLIC_ORIGINS` variable can list trusted comma-separated origins when a proxy
uses a different internal Host header. `/health` is the health-check route.

Test a local Docker build:

```sh
docker build -t aquascope-gpr .
docker run --rm -p 7860:7860 -v aquascope-data:/data aquascope-gpr
```

No paid hosting subscription or public backend was created during packaging.
