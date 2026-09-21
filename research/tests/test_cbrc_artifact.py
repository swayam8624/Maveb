import tempfile
import unittest
from pathlib import Path

from research.cbrc.artifact import (
    QoIResult,
    RevisionCertificateArtifact,
)


class CBRCArtifactTests(unittest.TestCase):
    def base(self, qoi):
        return RevisionCertificateArtifact(
            schema_version=1,
            git_sha="deadbeef",
            scene_id="scene",
            revision_id="rev",
            graph_version="graph-v1",
            bound_version="bounds-v1",
            hard_closure_nodes=1,
            repair_cone_nodes=2,
            total_nodes=5,
            fallback_full=False,
            stable=True,
            planner_work=2.0,
            full_work=5.0,
            qois={"rgb_linf": qoi},
            work_ledger={"gpuPublicationBytes": {"incremental": 10, "full": 100}},
        )

    def test_valid_artifact_writes(self):
        artifact = self.base(QoIResult(0.1, 0.08, 0.05))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "RevisionCertificate.json"
            artifact.write(path, require_oracle=True)
            self.assertTrue(path.exists())

    def test_actual_above_bound_fails(self):
        artifact = self.base(QoIResult(0.1, 0.08, 0.09))
        with self.assertRaisesRegex(ValueError, "actual > certified"):
            artifact.validate(require_oracle=True)

    def test_bound_above_epsilon_fails_stable_certificate(self):
        artifact = self.base(QoIResult(0.1, 0.11, 0.09))
        with self.assertRaisesRegex(ValueError, "exceeds tolerance"):
            artifact.validate(require_oracle=True)

    def test_oracle_is_required_for_final_evidence(self):
        artifact = self.base(QoIResult(0.1, 0.08, None))
        with self.assertRaisesRegex(ValueError, "missing full-reference"):
            artifact.validate(require_oracle=True)


if __name__ == "__main__":
    unittest.main()
