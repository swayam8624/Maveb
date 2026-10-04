# ADR 0001: Metal-native C++ core with a native macOS shell

Status: Accepted — 2026-07-12

## Decision

AETHER uses a C++23 engine and direct Metal backend. SwiftUI owns macOS document and workspace UI.
An Objective-C++ bridge exposes only AppKit views and immutable/status data to Swift; Metal objects
remain inside the bridge and engine.

The engine does not introduce a Vulkan/D3D-style abstraction. Metal 4 features are runtime-selected
optimizations with Metal 3-compatible fallbacks for the M1+ baseline.

## Consequences

- Render code can use Apple GPU features without lowest-common-denominator interfaces.
- The UI remains native and accessible while renderer ownership stays explicit in C++.
- Mixed-language lifetime and threading tests are mandatory.
- visionOS/iOS ports may reuse the engine but require new platform shells.
