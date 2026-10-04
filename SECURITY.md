# Security Policy

## Supported versions

Only the newest tagged AETHER release and the current `main` branch receive security fixes during
pre-1.0 development.

## Reporting

Do not open a public issue for a vulnerability. Use GitHub private vulnerability reporting for the
repository owner. Include the affected version, input file or reproduction, impact, and whether the
sample contains private capture data.

## Security boundaries

AETHER treats PLY, glTF, `.aether`, image, and reconstruction outputs as untrusted. Parsers must
enforce file-size, element-count, allocation, offset, decompression-ratio, path-traversal, and
integer-overflow limits before allocating or dispatching GPU work.

The application never requests signing certificates, notarization passwords, Sparkle private keys,
or dataset-service credentials through its project files. Secrets belong in the user Keychain or
CI secret store and must not be pasted into logs or bug reports.
