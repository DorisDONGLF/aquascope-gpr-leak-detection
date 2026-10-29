# Browser port validation â€” 28 October 2026

These tests check agreement with the existing Python pipeline. They are not an independent evaluation of leak-detection precision or recall. Real survey fixtures remain private.

| Check | Result |
| --- | --- |
| ONNX export vs PyTorch, random batches 1, 2, 8 | Presence error < 1e-6; localizer < 5.3e-6; localizer argmax unchanged |
| Preprocessing | All 77 inputs (128 Ã— 193) matched PyTorch exactly on a 267-sample SGY fixture |
| Browser WASM vs Python, one SGY | 77 windows, 2 candidates; identical center traces and XY |
| Five SGYs, two swaths | 385 windows, 5 candidates; identical centers, XY and merged membership; supports 5, 2, 2, 2, 2 |
| Maximum presence-logit difference | 0.00012923 |
| Channel alignment | Main CH3, CH4, CH5 and one neighboring swath matched Python; maximum aligned-position difference < 1e-12 m |
| Full vertical physical window | Numerical resampled matrix matched Python exactly on the tested primary fixture |
| GIS export | SHP, SHX and DXF bytes matched Python for synthetic selections; DBF attributes and CSV values matched, including Chinese notes |
| Actual browser detection | Separate-source version and standalone Pages bundle completed detection with WebAssembly |
| Review persistence | Decision and Chinese notes survived reload; selected-only export contained exactly the chosen point |
| Clear all reviews | Decisions and notes reset after confirmation; history and export selection retained |

Float32 ONNX opset 17 runs in ONNX Runtime Web 1.31.1 on WebAssembly CPU. Small kernel differences can affect cases extremely close to thresholds or tied scores. These fixtures do not establish equivalence for all SGY files or browsers.

PNGs preserve the full recorded vertical sample range and show 8 m / 16 m horizontal context. Canvas and Python image interpolation can differ slightly; alignment was checked numerically rather than by PNG byte equality.

## Selected metallic trace mute

The manual mode suggests amplitude outliers and mutes explicitly selected ranges. Unit checks cover empty selections, threshold equality, invalid bounds, overlapping ranges, first/last traces, existing zeros, extended textual headers, and exclusion of candidates centered on muted traces. The disabled operation retains the five-file Python parity results above.

A downloaded real SGY copy was checked byte by byte: for a 1,200-trace, 267-sample file, selecting traces 583–617 zeroed exactly 35 sample payloads. Every other byte, including trace headers and XY, matched the original. The original file was untouched. This is an integrity test, not a manhole identification test.

All 161 confirmed positive records were checked against amplitude statistics from their original full SGYs across four dates. Positive-center overlap with automatic suggestions was 105 / 161 at 3× median, 70 / 161 at 4×, and 45 / 161 at 5×. This demonstrates that automatic amplitude suppression would remove many known target centers; it does not measure manhole discrimination or postprocessing recall. No manhole-classifier accuracy is claimed.

## Larger imports — 29 October 2026

The browser guard was increased from 128 to 1,024 files while retaining the 512 MB per-file limit. Checks verify that 129 files are accepted, file 1,025 is reported as overflow rather than silently discarded, duplicate selections are removed, and quota states are handled for insufficient, limited, sufficient and unavailable estimates.

An actual browser run imported **129 repeated real SGY fragments** (320 traces each; 51.9 MB in total), scored **1,161 windows**, and completed detection. Repeated observations merged into one candidate. The interface reported 8.1 seconds for the scan on the test machine. These repeated fragments validate the importer and processing path above the old cap; they are not independent survey samples or a benchmark of 1,024 full-sized SGYs.

## All-file automatic mute — 29 October 2026

Automatic mode requires only selecting **Muted SGY** and starting detection. A real browser run processed five SGY fragments from two swaths at the 5× starting threshold without any per-file selection. All five files had audit records: 11, 13, 4, 0 and 0 traces were muted (28 total). Independent NumPy calculations on the original files reproduced every reported range. Detection scored 381 windows and returned five candidates. The unchanged raw mode still matched Python on 385 windows and five candidates.

Unit checks additionally cover automatic operation without manual ranges, independent handling of an all-zero file, the recorded automatic mode, and preservation of original bytes. These checks validate processing and provenance, not manhole classification, precision improvements or protection against missed leak targets.

## Linked channel map — 29 October 2026

Header-only XY parsing matched the full SGY reader exactly on five private SGY fragments. Analytic fixtures verify an 8 m footprint, reversed display edges, clipped file edges, preserved coordinate breaks, and no invented antenna offsets when channels share recorded XY. Background track simplification is limited to 0.02 m; active footprints retain all recorded positions. These are geometry consistency checks, not an independent geolocation accuracy assessment.

Actual standalone-browser QA used five SGYs from two swaths with all XY consistently shifted to an arbitrary public location. Their relative geometry and signal samples remained local. The run scored 385 windows and produced five candidates. LandsD road and English-label tiles loaded with the required logo and attribution. Clicking the map's CH3 control selected its B-scan; the primary next-channel control updated the map to CH4; a nearby-swath next-channel control selected CH2 and updated the map while preserving the upper CH4 image. Exact aligned distances shown in the local plan were 0.083 m, 0.000 m and 0.084 m for primary CH3–5. Existing-run geometry loaded without another detection. No console errors were observed. QA fixtures, screenshots and coordinates are excluded from the published archive.

## Center markers and per-swath relationship plans — 29 October 2026

The map now uses short ticks for valid B-scan edges and a dominant red, permanently labelled Candidate center. The same fixed candidate XY is used in every local diagram. Each displayed nearby-swath viewer has a separate plan combining blue primary channels and orange channels from that swath, with independent selected-channel state. Label positions are separated from track positions by leaders; the geometry itself is never spread out to separate names. Local plans load without requesting remote road tiles. Across/along axes are fitted independently and the diagram explicitly states this.

A pure geometry test covers 18 primary plus 18 nearby channels, shared candidate coordinates, label spacing of at least 40 SVG pixels, exact selected footprints, missing primary geometry, reversed tracks and coincident coordinates without artificial displacement. An actual standalone browser run imported 36 SGY fragments: repeated QA amplitudes with synthetic public-location headers, representing 18 channels in each of two swaths. It scored 2,772 windows, produced five merged candidates and displayed all 36 channel labels in the comparison plan. Read-only DOM bounding-box checks found zero same-band text overlaps. Horizontal scrolling preserved legible labels in the narrow review panel. These repeated fixtures are UI/integration checks, not additional training samples or independent survey validation.
