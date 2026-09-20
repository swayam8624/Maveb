import unittest

from research.cbrc.edges import (
    EdgeClass,
    RevisionEdge,
    certificate_transfer,
    exact_predecessors,
)


class CBRCEdgeRegistryTests(unittest.TestCase):
    def test_analytic_edge_enters_certificate_matrix(self):
        edges = [RevisionEdge(0, 1, EdgeClass.ANALYTIC, gain=0.25, bound_id="proof-v1")]
        K = certificate_transfer(2, edges)
        self.assertEqual(K[1, 0], 0.25)
        self.assertEqual(exact_predecessors(2, edges)[1], set())

    def test_empirical_edge_is_promoted_to_exact_predecessor(self):
        edges = [RevisionEdge(0, 1, EdgeClass.EMPIRICAL, gain=0.2)]
        K = certificate_transfer(2, edges)
        self.assertEqual(K[1, 0], 0.0)
        self.assertEqual(exact_predecessors(2, edges)[1], {0})

    def test_hard_edge_cannot_smuggle_gain(self):
        with self.assertRaises(ValueError):
            certificate_transfer(
                2,
                [RevisionEdge(0, 1, EdgeClass.HARD, gain=0.1)],
            )

    def test_analytic_edge_requires_bound_provenance(self):
        with self.assertRaises(ValueError):
            certificate_transfer(
                2,
                [RevisionEdge(0, 1, EdgeClass.ANALYTIC, gain=0.1)],
            )


if __name__ == "__main__":
    unittest.main()
