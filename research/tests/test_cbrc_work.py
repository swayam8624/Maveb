import unittest

from research.cbrc.work import WorkCostModel


class CBRCWorkCostModelTests(unittest.TestCase):
    def model(self):
        return WorkCostModel.from_mapping(
            {
                "version": "fixture-v1",
                "cost_unit": "ms",
                "domains": {
                    "gaussiansUpdated": {
                        "unit": "gaussians",
                        "cost_per_unit": 0.01,
                    },
                    "gpuPublicationBytes": {
                        "unit": "bytes",
                        "cost_per_unit": 1e-6,
                    },
                },
            }
        )

    def test_heterogeneous_native_units_are_converted_before_sum(self):
        ledger = {
            "gaussiansUpdated": {
                "incremental": 10,
                "full": 100,
                "unit": "gaussians",
            },
            "gpuPublicationBytes": {
                "incremental": 1000,
                "full": 10000,
                "unit": "bytes",
            },
        }
        model = self.model()
        self.assertAlmostEqual(model.estimate(ledger, field="incremental"), 0.101)
        self.assertAlmostEqual(model.estimate(ledger, field="full"), 1.01)

    def test_nonzero_unmodelled_domain_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "no frozen scalar cost"):
            self.model().estimate(
                {
                    "tsdfBlocksRead": {
                        "incremental": 1,
                        "full": 10,
                        "unit": "blocks",
                    }
                },
                field="incremental",
            )

    def test_unit_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "model unit"):
            self.model().estimate(
                {
                    "gaussiansUpdated": {
                        "incremental": 1,
                        "full": 1,
                        "unit": "bytes",
                    }
                },
                field="incremental",
            )


if __name__ == "__main__":
    unittest.main()
