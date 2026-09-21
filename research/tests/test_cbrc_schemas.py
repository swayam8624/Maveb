import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "research" / "schema"
CONFIG = ROOT / "research" / "config"


class CBRCSchemaContractTests(unittest.TestCase):
    def load(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_all_cbrc_schemas_parse_and_are_v1(self):
        paths = sorted(SCHEMA.glob("cbrc_*.schema.json"))
        self.assertGreaterEqual(len(paths), 4)
        for path in paths:
            with self.subTest(path=path.name):
                payload = self.load(path)
                self.assertEqual(
                    payload["$schema"],
                    "https://json-schema.org/draft/2020-12/schema",
                )
                self.assertIn("$id", payload)
                self.assertEqual(payload["type"], "object")

    def test_work_cost_example_covers_v1_heterogeneous_domains(self):
        model = self.load(CONFIG / "cbrc_work_cost_model.example.json")
        self.assertEqual(model["schemaVersion"], 1)
        required = {
            "observationsInspected",
            "tsdfBlocksRead",
            "tsdfBlocksWritten",
            "meshCellsRegenerated",
            "meshPatchesRegenerated",
            "gaussiansInspected",
            "gaussiansUpdated",
            "texturePagesUpdated",
            "textureTexelsWritten",
            "materialStatesUpdated",
            "gpuPublicationBytes",
            "temporalPixelsInvalidated",
        }
        self.assertTrue(required.issubset(model["domains"]))

    def test_campaign_example_matches_capture_mode_contract(self):
        campaign = self.load(CONFIG / "cbrc_real_campaign.example.json")
        self.assertEqual(campaign["schemaVersion"], 1)
        self.assertGreaterEqual(
            len(campaign["cases"]), int(campaign["minimum_revisions"])
        )
        ids = set()
        for case in campaign["cases"]:
            self.assertNotIn(case["id"], ids)
            ids.add(case["id"])
            self.assertGreaterEqual(float(case["epsilon"]), 0.0)
            self.assertIn("revision", case)
            revision = case["revision"]
            self.assertEqual(len(revision["target"]), 3)
            camera = revision["camera"]
            self.assertEqual(len(camera["camera_world_position"]), 3)
            self.assertEqual(len(camera["world_to_camera"]), 16)

    def test_revision_row_schema_contains_safety_triplet(self):
        schema = self.load(SCHEMA / "cbrc_revision_row.schema.json")
        qoi = schema["properties"]["qois"]["additionalProperties"]
        required = set(qoi["required"])
        self.assertEqual(
            required,
            {
                "epsilon",
                "certified_bound",
                "measured_full_reference_error",
            },
        )

    def test_replay_example_uses_frozen_v1_versions(self):
        replay = self.load(CONFIG / "cbrc_gaussian_replay_manifest.example.json")
        self.assertEqual(
            replay["graph_version"], "gaussian-source-image-history-v1"
        )
        self.assertEqual(replay["bound_version"], "gaussian-image-temporal-v1")

    def test_native_certificate_schema_locks_artifact_identity(self):
        schema = self.load(SCHEMA / "cbrc_native_certificate.schema.json")
        self.assertEqual(
            schema["properties"]["artifact"]["const"],
            "maveb-cbrc-native-certificate",
        )
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 1)


if __name__ == "__main__":
    unittest.main()
