import unittest

from research.cbrc.edges import (
    EdgeClass,
    RevisionEdge,
    certificate_transfer,
    dependency_predecessors,
    exact_predecessors,
    hard_forward_closure,
    required_repair_closure,
)


class CBRCEdgeRegistryTests(unittest.TestCase):
    def test_analytic_edge_enters_certificate_matrix(self):
        edges = [RevisionEdge(0, 1, EdgeClass.ANALYTIC, gain=0.25, bound_id="proof-v1")]
        K = certificate_transfer(2, edges)
        self.assertEqual(K[1, 0], 0.25)
        self.assertEqual(exact_predecessors(2, edges)[1], set())
        self.assertEqual(dependency_predecessors(2, edges)[1], {0})

    def test_empirical_edge_is_promoted_to_exact_predecessor(self):
        edges = [RevisionEdge(0, 1, EdgeClass.EMPIRICAL, gain=0.2)]
        K = certificate_transfer(2, edges)
        self.assertEqual(K[1, 0], 0.0)
        self.assertEqual(exact_predecessors(2, edges)[1], {0})

    def test_hard_forward_closure_propagates_hard_and_empirical_only(self):
        edges = [
            RevisionEdge(0, 1, EdgeClass.HARD),
            RevisionEdge(1, 2, EdgeClass.EMPIRICAL, gain=0.3),
            RevisionEdge(2, 3, EdgeClass.ANALYTIC, gain=0.2, bound_id="proof-v1"),
        ]
        self.assertEqual(hard_forward_closure(4, edges, {0}), {0, 1, 2})

    def test_soft_to_hard_boundary_forces_exact_repair(self):
        edges = [
            RevisionEdge(0, 1, EdgeClass.ANALYTIC, gain=0.25, bound_id="proof-v1"),
            RevisionEdge(1, 2, EdgeClass.HARD),
        ]
        required = required_repair_closure(
            3,
            edges,
            physical_sources={0},
            true_change_bounds=[1.0, 0.25, 0.25],
        )
        self.assertEqual(required, {0, 1, 2})

    def test_zero_change_hard_target_need_not_be_repaired(self):
        edges = [
            RevisionEdge(0, 1, EdgeClass.ANALYTIC, gain=0.25, bound_id="proof-v1"),
            RevisionEdge(1, 2, EdgeClass.HARD),
        ]
        required = required_repair_closure(
            3,
            edges,
            physical_sources={0},
            true_change_bounds=[1.0, 0.25, 0.0],
        )
        self.assertEqual(required, {0})

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
