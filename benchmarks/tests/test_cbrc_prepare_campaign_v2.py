from __future__ import annotations

import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = load("cbrc_prepare_real_campaign_v2test", "benchmarks/scripts/cbrc_prepare_real_campaign.py")
v2 = load("cbrc_prepare_campaign_v2", "benchmarks/scripts/cbrc_prepare_campaign_v2.py")


def candidate(root: Path, stem: str, offset: float) -> base.Candidate:
    archive = root / f"{stem}.aetherworld"
    entities = {}
    owners = []
    for entity in range(1, 7):
        entities[entity] = {
            "id": entity,
            "translation": [offset + entity * 0.1, 0.1 * entity, 1.0],
        }
        owners.extend([entity] * (20 + entity * 5))
    count = len(owners)
    gaussian = Path(str(archive) + ".gaussians.r1.bin")
    ownership = Path(str(archive) + ".ownership.r1.bin")
    archive.write_text(json.dumps({"snapshots":[{"revision":1,"timestamp":1_000_000_000,"entities":list(entities.values())}]}))
    header = b"AETHGS\x00\x00" + struct.pack("<HHIQII",1,0,256,count,0,0)
    records = bytearray()
    for index in range(count):
        record = bytearray(256)
        struct.pack_into("<3f", record, 0, offset + index * 0.001, float(index % 7) * 0.01, 1.0)
        records.extend(record)
    gaussian.write_bytes(header + records)
    ownership.write_bytes(b"MVGOWNR\x00" + struct.pack("<IIQQ",1,32,count,0) + b"".join(struct.pack("<Q",o) for o in owners))
    return base.inspect_archive(archive)


class CampaignV2Tests(unittest.TestCase):
    def test_four_scenes_make_sixty_frozen_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidates = [candidate(root, f"scene-{i}", float(i)) for i in range(4)]
            campaign, freeze = v2.build(candidates, root / "freeze", cases_per_scene=15, work_cost_model=None)
            self.assertEqual(len(campaign["cases"]), 60)
            self.assertEqual(campaign["minimum_revisions"], 60)
            self.assertEqual(campaign["minimum_scenes"], 4)
            self.assertEqual(freeze["case_count"], 60)
            self.assertEqual(len({c["scene_id"] for c in campaign["cases"]}), 4)
            self.assertTrue(any(not c["revision"]["history_stable"] for c in campaign["cases"]))
            self.assertTrue(any(c["coupling_regime"] == "adversarial" for c in campaign["cases"]))
            self.assertEqual(campaign["campaignId"], "cbrc-public-real-v2.1-effective-edits")
            for case in campaign["cases"]:
                matrix = case["matrix_tags"]
                self.assertGreater(matrix["applied_delta_world"], v2.WORLD_DIFF_TRANSLATION_THRESHOLD)
                self.assertGreaterEqual(matrix["applied_delta_world"], matrix["requested_delta_world"])

    def test_subthreshold_requested_edit_is_clamped_before_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidates = [candidate(root, "scene-a", 0.0), candidate(root, "scene-b", 1.0)]
            campaign, freeze = v2.build(candidates, root / "freeze", cases_per_scene=1, work_cost_model=None)
            case = campaign["cases"][0]
            matrix = case["matrix_tags"]
            self.assertLess(matrix["requested_delta_world"], v2.WORLD_DIFF_TRANSLATION_THRESHOLD)
            self.assertEqual(matrix["applied_delta_world"], v2.MINIMUM_EFFECTIVE_TRANSLATION)
            self.assertEqual(freeze["world_diff_translation_threshold"], v2.WORLD_DIFF_TRANSLATION_THRESHOLD)
            self.assertEqual(freeze["minimum_effective_translation"], v2.MINIMUM_EFFECTIVE_TRANSLATION)

    def test_case_archives_are_independent_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            c = candidate(root, "scene", 0.0)
            campaign, _ = v2.build([c, candidate(root, "scene2", 1.0)], root / "freeze", cases_per_scene=2, work_cost_model=None)
            paths = [Path(case["revision"]["archive"]) for case in campaign["cases"]]
            self.assertEqual(len(paths), len(set(paths)))
            self.assertTrue(all(path.is_file() for path in paths))


if __name__ == "__main__":
    unittest.main()
