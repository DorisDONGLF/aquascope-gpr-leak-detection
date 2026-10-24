# AquaScope GPR Leak Detection

English GPR candidate detection and expert review workspace. Uses the existing Presence v3 detector and Horizontal Localizer v1 without retraining.

## Local use

Python 3.11+ is required. Install `requirements.txt`, then run `python server/app.py --port 8765` and open `http://127.0.0.1:8765/`.

Import big-endian int32 SEG-Y format 2 files. Review ranked candidates, compare merged hits by channel/swath, mark decisions, and export CSV, Geolitix DXF or Shapefile. Current review results can be cleared per run; edit history is retained.

## Sharing and deployment

Publishing this repository alone does not host the Python detection service. GitHub Pages can host a static interface; model inference requires a compatible runtime. See [DEPLOYMENT.md](DEPLOYMENT.md) for the complete Docker deployment, hosting options and persistence requirements. No public inference endpoint is live yet.

No original SGY survey files, survey coordinates, candidate images, existing detection runs, expert identities or review notes are included. Runtime uploads and results are excluded from Git. The original example data and known-point comparisons are unavailable unless supplied locally.

## Model interpretation

Model logits determine review priority, not calibrated leak probability. The model finds signals similar to training examples and estimates a horizontal center. Expert review is required. Blue alignment lines show the fixed primary candidate projected onto each recorded track; dashed green lines show the AI center.

## Third-party software

Proj4js is included under its original MIT license in `server/static/vendor/proj4-LICENSE.md`. The workspace visual conventions follow the AquaScope family, referencing the lab project `zhoumaneo/aquascope_gpr_postprocessing`.

For the deployable server, run `python server/public_server.py --host 127.0.0.1 --port 7860` locally, or build the included Dockerfile on a hosting platform. Different browsers use separate workspaces.
