import unittest

import numpy as np

from research.cbrc.core import QoI, certify_cone, effectivity, greedy_minimum_work_cone


class CBRCCertificateTests(unittest.TestCase):
    def qoi_identity(self, n, eps):
        return [QoI("state", np.eye(n), eps)]

    def test_chain_certificate(self):
        K = np.zeros((3, 3))
        K[1, 0] = 0.2
        K[2, 1] = 0.2
        z = np.array([1.0, 0.2, 0.04])

        cert = certify_cone(
            K_cert=K,
            source=np.array([1.0, 0.0, 0.0]),
            true_change_bound=z,
            cone={0},
            exact_predecessors=[set(), set(), set()],
            work=np.ones(3),
            qois=self.qoi_identity(3, 0.25),
        )
        self.assertTrue(cert.stable)
        self.assertTrue(cert.passes)
        self.assertLessEqual(cert.bound_by_qoi["state"], 0.25)

    def test_dag_transient_fanout_remains_visible(self):
        K = np.zeros((5, 5))
        K[1:, 0] = 0.8
        cert = certify_cone(
            K_cert=K,
            source=np.array([1, 0, 0, 0, 0], float),
            true_change_bound=np.array([1, 0.8, 0.8, 0.8, 0.8], float),
            cone={0},
            exact_predecessors=[set() for _ in range(5)],
            work=np.ones(5),
            qois=self.qoi_identity(5, 1.0),
        )
        self.assertTrue(cert.stable)
        self.assertGreaterEqual(cert.transient_amplification, 1.0)

    def test_unstable_exterior_is_rejected(self):
        K = np.array(
            [
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 1.1],
                [0.0, 1.1, 0.0],
            ]
        )
        cert = certify_cone(
            K_cert=K,
            source=np.array([1.0, 0.0, 0.0]),
            true_change_bound=np.ones(3),
            cone={0},
            exact_predecessors=[set(), set(), set()],
            work=np.ones(3),
            qois=self.qoi_identity(3, 0.1),
        )
        self.assertFalse(cert.stable)
        self.assertFalse(cert.passes)

    def test_predecessor_inconsistency_is_rejected(self):
        cert = certify_cone(
            K_cert=np.zeros((2, 2)),
            source=np.ones(2),
            true_change_bound=np.ones(2),
            cone={1},
            exact_predecessors=[set(), {0}],
            work=np.ones(2),
            qois=self.qoi_identity(2, 1.0),
        )
        self.assertFalse(cert.stable)
        self.assertIn("predecessor", cert.reason)

    def test_greedy_can_fall_back_to_full(self):
        K = np.zeros((4, 4))
        K[1:, 0] = 1.0
        cert = greedy_minimum_work_cone(
            K_cert=K,
            source=np.array([1.0, 0.0, 0.0, 0.0]),
            true_change_bound=np.ones(4),
            hard_closure={0},
            exact_predecessors=[set() for _ in range(4)],
            work=np.ones(4),
            qois=self.qoi_identity(4, 0.0),
        )
        self.assertTrue(cert.passes)
        self.assertTrue(cert.used_full_rebuild)
        self.assertEqual(cert.work, cert.full_work)

    def test_effectivity(self):
        self.assertEqual(effectivity(0.2, 0.1), 2.0)


if __name__ == "__main__":
    unittest.main()
