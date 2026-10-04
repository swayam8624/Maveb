#!/usr/bin/env python3

import json
import pathlib
import subprocess
import sys


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: assert-photogrammetry-contract.py <tool> <images> <output>"
        )

    tool = pathlib.Path(sys.argv[1]).resolve()
    images = pathlib.Path(sys.argv[2]).resolve()
    output = pathlib.Path(sys.argv[3]).resolve()
    result = subprocess.run(
        [
            str(tool),
            str(images),
            "--output",
            str(output),
            "--detail",
            "preview",
            "--dry-run",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"dry-run failed with exit {result.returncode}: {result.stderr.strip()}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(f"dry-run emitted invalid JSON: {result.stdout!r}") from error

    expected = {
        "ok": True,
        "dryRun": True,
        "images": 3,
        "input": str(images),
        "output": str(output),
        "detail": "preview",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise AssertionError(
                f"unexpected {key}: expected {value!r}, received {payload.get(key)!r}"
            )
    if not isinstance(payload.get("runtimeSupported"), bool):
        raise AssertionError("runtimeSupported must be a JSON boolean")
    if output.exists():
        raise AssertionError("dry-run must not create the requested model")

    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
