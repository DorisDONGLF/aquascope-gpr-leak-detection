# Deployment and rebuilding

## Free GitHub Pages edition

The static application is **docs/index.html**. It contains the interface, SGY processing, PNG rendering, exports and embedded ONNX models. Python is not involved in detection on the published site.

1. Publish docs/index.html and docs/.nojekyll.
2. In **Settings â†’ Pages**, select **Deploy from a branch**, **main**, **/docs**, then **Save**.
3. Wait for deployment and use the HTTPS URL shown by GitHub.
4. Import a small SGY, run detection, review, refresh and export before sharing.

ONNX Runtime Web 1.31.1 is loaded from https://cdn.jsdelivr.net/npm/onnxruntime-web@1.31.1/dist/ . A dedicated Web Worker uses one-thread WebAssembly CPU. Cross-origin-isolation headers are unnecessary. First-run network access is required; this release does not install an offline service worker.

## Rebuild from source

Extract **aquascope-source.zip**. It contains browser/, tools/, server/, model_v1/ and model_v3/. Private validation surveys and review records are excluded.

Existing ONNX models are ready. After editing source modules, run:

```sh
python tools/build_browser.py
python -m http.server 8767 --bind 127.0.0.1
```

Open http://127.0.0.1:8767/docs/ for the exact Pages bundle, or /browser/ for separate source assets with the bundled local runtime. Commit the rebuilt docs/index.html. Do not open it as a file:// document.

To re-export checkpoints, install PyTorch, NumPy, ONNX and ONNX Runtime in an isolated Python environment and run `python tools/export_onnx.py`. The exporter uses opset 17, dynamic batches and float32 weights. It does not retrain or quantize. browser/models/manifest.json records checkpoint and ONNX hashes. Rebuild Pages after conversion.

## Storage and limits

Files, jobs, images, scores, selections and history are stored in IndexedDB under the site origin. There is no central database or cross-device synchronization. Browser quotas, memory and CPU constrain survey size. Import in batches, keep the tab open while running, and export regularly. Interrupted jobs are reported when revisiting.

Google Maps is initially disabled. Its optional map view or external link sends a location to Google. Detector inputs and notes are not sent to GitHub or the CDN.

## Optional Python application

Install requirements.txt and run `python server/app.py --port 8765` for local use. The separate public_server.py and Dockerfile can support a hosted Python deployment with isolated per-browser workspaces and a persistent /data volume. No such host is needed for the browser version.

Do not expose local-only app.py to the internet. public_server.py assumes a single container and inference queue. Shared multi-expert projects would require separate identity, authorization and synchronization support.
