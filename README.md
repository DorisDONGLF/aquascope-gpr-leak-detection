# AquaScope GPR Leak Detection

English SGY signal detection, aligned channel comparison, expert review and point export. Presence v3 and Horizontal Localizer v1 run on the visitor's computer using ONNX Runtime Web. No Python server, account or paid inference host is required for the browser edition.

## Use the application

Open the repository's **GitHub Pages** link under Deployments / Settings â†’ Pages. Choose **Import data**, select SGY files, and **Start detection**. Review candidates and export CSV, Geolitix DXF or a Shapefile ZIP. PNG images and a review atlas ZIP are also available.

Use current desktop Chrome or Edge. Supported input is big-endian int32 SEG-Y sample format 2, up to 128 files per run and 512 MB per file. These are input limits, not a guarantee that every computer can handle their combined size. Import large surveys in swath-sized batches and keep the tab open during detection. The first run downloads approximately 15 MB of pinned WebAssembly runtime files from jsDelivr.

Files, coordinates, PNGs and reviews stay in this browser's IndexedDB. Refreshing preserves them; clearing site storage removes them. Different computers and browser profiles have independent records. There is no cross-device expert synchronization. Export your work regularly. Google Maps is optional: enabling it or opening its link shares the selected location with Google.

No original survey files, coordinate datasets, existing results or expert notes are included in this repository.

## Review and export

### Inspect and mute metallic reflections

Use **Inspect / mute SGY ranges** during import, or **Inspect / mute SGY** on a completed run. The tool suggests traces whose mean absolute amplitude exceeds a chosen multiple of the median of nonzero traces. Suggestions are **not** manhole classifications. Nothing is selected automatically: choose ranges confirmed as metal/manhole reflections, or enter known trace bounds, and compare the original and muted previews with the same gain.

Download a separate **muted SGY** and a JSON mute log, or use the selected ranges before a new detection. Existing results and reviews are not altered. Only the selected sample payloads are zeroed; all headers, trace numbers, coordinates, vertical sample counts and file length are preserved. Mute operates on whole traces and can also hide subsurface targets below a metal cover. It does not reconstruct signals obscured by metal.

The optional operation defaults off. In a private audit of all 161 confirmed positive records, applying the amplitude suggestion rule automatically would flag 105 positive centers at 3× median, 70 at 4×, and 45 at 5×. These are center-overlap counts, not measured detector error rates. This is why explicit range selection is required. The implementation follows the documented idea in [Geolitix metallic-reflection processing](https://docs.geolitix.com/layers/gpr-processing.html#remove-metallic-reflections); it is not a reproduction of Geolitix's proprietary implementation.

- Compare merged-hit channels, ordered by channel number within each swath. A fixed primary candidate XY is projected onto each recorded track; other swaths are ordered by distance.
- Decisions are **Suspected leak**, **No leak signal**, or **Uncertain**. The latest saved decision applies; edit history remains available. **Clear all reviews** resets the current run's decisions and notes while retaining history.
- Export manually selected candidates, matching candidates from all filtered pages, or all candidates when neither selection nor filters are active. An explicit empty selection never falls back to all points.
- SHP/DXF preserve recorded XY. Select the correct CRS for Shapefile metadata. The map assumes the confirmed Hong Kong 1980 Grid (EPSG:2326).

Model logits determine review priority, not calibrated leak probability. The detector finds signals similar to training examples and estimates a horizontal center. Expert interpretation is required.

## Source and deployment

**docs/index.html** is the complete Pages application with embedded ONNX models. Source modules, build tools, original checkpoints and the optional Python application are in **aquascope-source.zip**. Extract it for the full source tree. See [DEPLOYMENT.md](DEPLOYMENT.md).

A private five-file, two-swath validation scored 385 windows and produced five candidates. Candidate centers, XY and merged membership matched Python; maximum presence-logit difference was 0.000130. This checks the port's consistency, not accuracy on new surveys. See [VALIDATION.md](VALIDATION.md).

[Third-party notices](THIRD_PARTY_NOTICES.md) and original licenses are included. The interface follows the AquaScope visual conventions used in the lab project `zhoumaneo/aquascope_gpr_postprocessing`.
