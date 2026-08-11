"""Run inside Blender to convert an Apple photogrammetry USDZ to a textured GLB."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def arguments() -> tuple[Path, Path]:
    if "--" not in sys.argv:
        raise ValueError("expected Blender arguments after --")
    values = sys.argv[sys.argv.index("--") + 1 :]
    if len(values) != 2:
        raise ValueError("usage: blender --background --python convert-usdz-to-glb.py -- input.usdz output.glb")
    source, output = map(lambda value: Path(value).expanduser().resolve(), values)
    if not source.is_file() or source.suffix.lower() != ".usdz":
        raise ValueError(f"input is not a USDZ file: {source}")
    if output.suffix.lower() != ".glb":
        raise ValueError("output must use the .glb extension")
    return source, output


def main() -> None:
    import bpy

    source, output = arguments()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = bpy.ops.wm.usd_import(filepath=str(source), import_materials=True)
    if "FINISHED" not in result:
        raise RuntimeError("Blender USD importer did not finish")
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("USDZ contained no mesh objects")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.export_scene.gltf(
        filepath=str(output), export_format="GLB", export_yup=True, export_materials="EXPORT"
    )
    if "FINISHED" not in result or not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("Blender glTF exporter did not produce a GLB")
    print(json.dumps({"ok": True, "input": str(source), "output": str(output),
                      "objects": len(meshes), "bytes": output.stat().st_size}, sort_keys=True))


if __name__ == "__main__":
    main()
