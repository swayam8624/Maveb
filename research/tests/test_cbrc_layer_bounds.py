import random
import unittest

from research.cbrc.layer_bounds import (
    effective_gaussian_alpha,
    gaussian_pixel_revision_bound,
    temporal_history_decay_bound,
    temporal_revision_bound,
)


def render(layers, background):
    layers = sorted(layers, key=lambda x: x[0])
    t = 1.0
    out = [0.0, 0.0, 0.0]
    for _, alpha, rgb in layers:
        for c in range(3):
            out[c] += t * alpha * rgb[c]
        t *= 1.0 - alpha
    for c in range(3):
        out[c] += t * background[c]
    return out


class CBRCLayerBoundTests(unittest.TestCase):
    def test_renderer_alpha_semantics(self):
        self.assertEqual(effective_gaussian_alpha(1.0, 9.1), 0.0)
        self.assertAlmostEqual(effective_gaussian_alpha(1.0, 0.0), 0.99)
        self.assertEqual(effective_gaussian_alpha(0.001, 0.0), 0.0)

    def test_random_gaussian_interleavings(self):
        rng = random.Random(20260920)
        cap = 2.5
        for _ in range(10000):
            unchanged = [
                (
                    rng.uniform(-3, 3),
                    0.7 * rng.random(),
                    [cap * rng.random() for _ in range(3)],
                )
                for _ in range(rng.randrange(13))
            ]
            before = [
                (
                    rng.uniform(-3, 3),
                    0.4 * rng.random(),
                    [cap * rng.random() for _ in range(3)],
                )
                for _ in range(1 + rng.randrange(6))
            ]
            after = [
                (
                    rng.uniform(-3, 3),
                    0.4 * rng.random(),
                    [cap * rng.random() for _ in range(3)],
                )
                for _ in range(1 + rng.randrange(6))
            ]
            bg = [cap * rng.random() for _ in range(3)]
            old = render(unchanged + before, bg)
            new = render(unchanged + after, bg)
            actual = max(abs(a - b) for a, b in zip(old, new))
            bound = gaussian_pixel_revision_bound(
                [x[1] for x in before],
                [x[1] for x in after],
                cap,
            ).rgb_linf_bound
            self.assertLessEqual(actual, bound + 1e-12)

    def test_random_temporal_clamp_blend(self):
        rng = random.Random(7)
        for _ in range(10000):
            oc, nc, oh, nh = [rng.random() for _ in range(4)]
            ol, ou = sorted([rng.random(), rng.random()])
            nl, nu = sorted([rng.random(), rng.random()])
            w = rng.random()
            clamp = lambda x, lo, hi: min(max(x, lo), hi)
            old = (1 - w) * oc + w * clamp(oh, ol, ou)
            new = (1 - w) * nc + w * clamp(nh, nl, nu)
            cert = temporal_revision_bound(
                current_error_bound=abs(nc - oc),
                history_error_bound=abs(nh - oh),
                neighborhood_extrema_error_bound=max(abs(nl - ol), abs(nu - ou)),
                history_weight=w,
                validation_decision_stable=True,
            )
            self.assertLessEqual(abs(new - old), cert.resolved_output_bound + 1e-12)

    def test_unstable_temporal_validation_falls_hard(self):
        cert = temporal_revision_bound(
            current_error_bound=0.02,
            history_error_bound=1.0,
            neighborhood_extrema_error_bound=1.0,
            history_weight=0.9,
            validation_decision_stable=False,
        )
        self.assertTrue(cert.requires_hard_invalidation)
        self.assertEqual(cert.resolved_output_bound, 0.02)

    def test_history_decay(self):
        self.assertAlmostEqual(temporal_history_decay_bound(1.0, 0.9, 10), 0.9**10)


if __name__ == "__main__":
    unittest.main()
