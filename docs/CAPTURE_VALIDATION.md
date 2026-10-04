# Capture validation

`aether-capture validate` inspects actual image content before an expensive reconstruction job. It
uses macOS ImageIO for decoding and metadata, creates bounded analysis thumbnails, and reports a
stable JSON schema suitable for Studio and automation.

```bash
build/debug/tools/aether-capture/aether-capture validate dataset/images --json
```

The validator rejects unreadable supported image files and too-small sets. For every decodable
image it records dimensions, file size, mean and standard deviation of luminance, a
Laplacian-energy sharpness score, and available EXIF exposure, aperture, ISO, focal length, make,
and model. Dataset warnings currently cover images whose sharpness is far below the set median and
luminance spreads above 1.5 stops. Working-space estimates use 16 bytes per decoded source pixel;
they are planning estimates, not measured peak memory.

Sharpness and luminance are relative capture checks, not photographic-quality scores. HDR brackets
can intentionally trigger exposure warnings. After COLMAP sparse mapping, `aether-reconstruct`
performs a separate evidence-based pose/overlap gate and writes `pose-coverage.json`; that downstream
check does not make the preflight validator capable of predicting feature matches. Reconstruction
should not be described as fully capture-validated until a real-image integration run is complete.
