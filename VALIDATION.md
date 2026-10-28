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
