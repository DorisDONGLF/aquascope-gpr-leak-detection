# AquaScope GPR Leak Detection

English SGY signal detection, aligned channel comparison, expert review and point export. Presence v3 and Horizontal Localizer v1 run on the visitor's computer using ONNX Runtime Web. No Python server, account or paid inference host is required for the browser edition.

## Use the application

Open the repository's **GitHub Pages** link under Deployments / Settings â†’ Pages. Choose **Import data**, select SGY files, and **Start detection**. Review candidates and export CSV, Geolitix DXF or a Shapefile ZIP. PNG images and a review atlas ZIP are also available.

Use current desktop Chrome or Edge. The browser edition supports big-endian int32 SEG-Y sample format 2, up to **1,024 files per run** and **512 MB per file**. Files are scanned sequentially. The importer displays the selected count, total size and estimated remaining browser storage, and checks capacity before saving the input files. A batch whose source files exceed the reported available space is rejected before import. Limited space for result images is highlighted separately; storage estimates do not guarantee that a complete run will fit. Available memory and the largest SGY also affect practical capacity. Import large surveys in batches that keep each swath's channels together, and keep the tab open during detection. The first run downloads approximately 15 MB of pinned WebAssembly runtime files from jsDelivr. The optional legacy Python edition retains its separate 128-file guard.

Files, coordinates, PNGs and reviews stay in this browser's IndexedDB. Refreshing preserves them; clearing site storage removes them. Different computers and browser profiles have independent records. There is no cross-device expert synchronization. Export your work regularly. Google Maps is optional: enabling it or opening its link shares the selected location with Google.

No original survey files, coordinate datasets, existing results or expert notes are included in this repository.

## Review and export

### Inspect and mute metallic reflections

During import, choose **Original SGY** or **Muted SGY · All files**. Original input is selected by default. Choosing muted input changes the action to **Mute all & detect**: every file gets its own automatic amplitude mask, those whole traces are zeroed in a working copy, and the same detector/localizer processes that copy. No per-file review or selection is required. The starting threshold is **5×** the median of nonzero trace mean-absolute amplitudes. This is an experimental starting setting, not a validated manhole threshold.

Results show a per-file mute report, including files with zero flagged traces, and **Download all mute ranges** exports the full audit. **Mute settings / optional preview** allows threshold adjustment and before/after comparison. The existing edited-range mode remains available inside these optional settings. **Inspect / mute SGY** also lets you download a separate processed SGY. Detection, gallery PNGs and point-export provenance all use the run's recorded input mode. Existing results and reviews are not altered. Only masked sample payloads are zeroed; all headers, trace numbers, coordinates, vertical sample counts and file length are preserved. Whole-trace mute can hide subsurface targets below a cover and does not reconstruct obscured signals.

Automatic masks are **not** manhole classifications. In a private audit of all 161 confirmed positive records, the rule flagged 105 positive centers at 3× median, 70 at 4×, and 45 at 5×. These are overlap counts, not measured detector error rates. Raw detection remains the default; automatic mute is an explicit user choice. Residual or boundary detections can remain. The implementation follows the documented idea in [Geolitix metallic-reflection processing](https://docs.geolitix.com/layers/gpr-processing.html#remove-metallic-reflections); it is not a reproduction of Geolitix's proprietary implementation.

- Compare merged-hit channels, ordered by channel number within each swath. A fixed primary candidate XY is projected onto each recorded track; other swaths are ordered by distance.
- Decisions are **Suspected leak**, **No leak signal**, or **Uncertain**. The latest saved decision applies; edit history remains available. **Clear all reviews** resets the current run's decisions and notes while retaining history.
- Export manually selected candidates, matching candidates from all filtered pages, or all candidates when neither selection nor filters are active. An explicit empty selection never falls back to all points.
- SHP/DXF preserve recorded XY. Select the correct CRS for Shapefile metadata. The map assumes the confirmed Hong Kong 1980 Grid (EPSG:2326).

Model logits determine review priority, not calibrated leak probability. The detector finds signals similar to training examples and estimates a horizontal center. Expert interpretation is required.

## Source and deployment

**docs/index.html** is the complete Pages application with embedded ONNX models. Source modules, build tools, original checkpoints and the optional Python application are in **aquascope-source.zip**. Extract it for the full source tree. See [DEPLOYMENT.md](DEPLOYMENT.md).

A private five-file, two-swath validation scored 385 windows and produced five candidates. Candidate centers, XY and merged membership matched Python; maximum presence-logit difference was 0.000130. This checks the port's consistency, not accuracy on new surveys. See [VALIDATION.md](VALIDATION.md).

[Third-party notices](THIRD_PARTY_NOTICES.md) and original licenses are included. The interface follows the AquaScope visual conventions used in the lab project `zhoumaneo/aquascope_gpr_postprocessing`.
