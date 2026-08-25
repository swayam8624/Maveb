import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks" / "scripts" / "ca1m_u3_pose_preflight.py"
SPEC = importlib.util.spec_from_file_location("ca1m_u3_pose_preflight", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)


class Ca1mU3PosePreflightTests(unittest.TestCase):
    def test_quantile_indices_use_frozen_nearest_tie_lower_rule(self):
        self.assertEqual(preflight.quantile_indices(10, 4), [0, 3, 6, 9])
        self.assertEqual(preflight.quantile_indices(4, 3), [0, 1, 3])

    def test_cross_projection_prefers_camera_to_world_interpretation(self):
        import numpy as np

        height = 64
        width = 64
        fx = 80.0
        fy = 80.0
        cx = 31.5
        cy = 31.5
        intrinsics = (fx, fy, cx, cy)

        source_depth = np.full((height, width), 2.0, dtype=np.float64)
        target_depth = np.full((height, width), 2.0, dtype=np.float64)

        source_pose = np.eye(4, dtype=np.float64)
        target_pose = np.eye(4, dtype=np.float64)
        target_pose[0, 3] = 0.10

        direct = preflight.cross_project(
            source_depth,
            intrinsics,
            source_pose,
            target_depth,
            intrinsics,
            target_pose,
            camera_to_world=True,
            pixel_stride=4,
        )
        inverse = preflight.cross_project(
            source_depth,
            intrinsics,
            source_pose,
            target_depth,
            intrinsics,
            target_pose,
            camera_to_world=False,
            pixel_stride=4,
        )

        self.assertGreater(direct[0], 100)
        self.assertGreater(inverse[0], 100)
        self.assertAlmostEqual(direct[1], 0.0, places=12)
        self.assertAlmostEqual(inverse[1], 0.0, places=12)

        tilted_target_pose = np.eye(4, dtype=np.float64)
        angle = np.deg2rad(5.0)
        tilted_target_pose[:3, :3] = np.array(
            [
                [np.cos(angle), 0.0, np.sin(angle)],
                [0.0, 1.0, 0.0],
                [-np.sin(angle), 0.0, np.cos(angle)],
            ],
            dtype=np.float64,
        )
        tilted_target_pose[0, 3] = 0.10

        yy, xx = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")
        rays_x = (xx - cx) / fx
        rays_y = (yy - cy) / fy
        target_rays = np.stack((rays_x, rays_y, np.ones_like(rays_x)), axis=-1)
        rotation = tilted_target_pose[:3, :3]
        translation = tilted_target_pose[:3, 3]
        world_directions = target_rays @ rotation.T
        world_origins = np.broadcast_to(translation, world_directions.shape)
        scale = (2.0 - world_origins[..., 2]) / world_directions[..., 2]
        target_depth = scale

        direct = preflight.cross_project(
            source_depth,
            intrinsics,
            source_pose,
            target_depth,
            intrinsics,
            tilted_target_pose,
            camera_to_world=True,
            pixel_stride=4,
        )
        inverse = preflight.cross_project(
            source_depth,
            intrinsics,
            source_pose,
            target_depth,
            intrinsics,
            tilted_target_pose,
            camera_to_world=False,
            pixel_stride=4,
        )

        self.assertIsNotNone(direct[1])
        self.assertIsNotNone(inverse[1])
        self.assertLess(direct[1], 0.01)
        self.assertGreater(inverse[1], direct[1] + 0.02)


if __name__ == "__main__":
    unittest.main()
