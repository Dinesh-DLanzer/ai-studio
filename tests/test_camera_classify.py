"""Unit tests for camera motion classification."""
import math
import random
import unittest

from aistudio.storyboard.camera_classify import classify


def make_look_at_matrix(pos, target, world_up=(0.0, 0.0, 1.0)):
    """Construct a 4x4 row-major camera matrix looking at target."""
    px, py, pz = pos
    tx, ty, tz = target

    fx, fy, fz = tx - px, ty - py, tz - pz
    flen = math.sqrt(fx * fx + fy * fy + fz * fz)
    if flen < 1e-9:
        fx, fy, fz = 0.0, 1.0, 0.0
    else:
        fx, fy, fz = fx / flen, fy / flen, fz / flen

    # Right = Forward x World Up
    wx, wy, wz = world_up
    rx = fy * wz - fz * wy
    ry = fz * wx - fx * wz
    rz = fx * wy - fy * wx
    rlen = math.sqrt(rx * rx + ry * ry + rz * rz)
    if rlen < 1e-9:
        rx, ry, rz = 1.0, 0.0, 0.0
    else:
        rx, ry, rz = rx / rlen, ry / rlen, rz / rlen

    # Camera Up = Right x Forward
    ux = ry * fz - rz * fy
    uy = rz * fx - rx * fz
    uz = rx * fy - ry * fx

    # Backward vector = -Forward
    bx, by, bz = -fx, -fy, -fz

    # Row-major 4x4:
    # Row 0: Rx, Ux, Bx, Px
    # Row 1: Ry, Uy, By, Py
    # Row 2: Rz, Uz, Bz, Pz
    # Row 3: 0,  0,  0,  1
    return [
        [rx, ux, bx, px],
        [ry, uy, by, py],
        [rz, uz, bz, pz],
        [0.0, 0.0, 0.0, 1.0],
    ]


def make_fixed_matrix(pos, forward=(0.0, 1.0, 0.0), world_up=(0.0, 0.0, 1.0)):
    """Matrix with given position and fixed orientation."""
    px, py, pz = pos
    target = (px + forward[0], py + forward[1], pz + forward[2])
    return make_look_at_matrix(pos, target, world_up)


class TestCameraClassify(unittest.TestCase):
    def setUp(self):
        self.fps = 24

    def test_static(self):
        samples = [make_fixed_matrix((0.0, -10.0, 0.0)) for _ in range(30)]
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "static")
        self.assertEqual(res["speed"], "slow")
        self.assertGreaterEqual(res["confidence"], 0.9)
        self.assertIn("evidence", res)

    def test_dolly_in(self):
        # Moving forward along view vector (+Y)
        samples = [
            make_fixed_matrix((0.0, -10.0 + i * 0.1, 0.0))
            for i in range(30)
        ]
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "dolly-in")
        self.assertIn(res["speed"], ["normal", "fast", "slow"])
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_dolly_out(self):
        # Moving backward along view vector (-Y)
        samples = [
            make_fixed_matrix((0.0, -10.0 - i * 0.1, 0.0))
            for i in range(30)
        ]
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "dolly-out")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_truck_right(self):
        # Moving right along local +X axis
        samples = [
            make_fixed_matrix((i * 0.1, -10.0, 0.0))
            for i in range(30)
        ]
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "truck-right")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_truck_left(self):
        # Moving left along local -X axis
        samples = [
            make_fixed_matrix((-i * 0.1, -10.0, 0.0))
            for i in range(30)
        ]
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "truck-left")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_pedestal_up(self):
        # Moving up along local +Z axis
        samples = [
            make_fixed_matrix((0.0, -10.0, i * 0.1))
            for i in range(30)
        ]
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "pedestal-up")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_pedestal_down(self):
        # Moving down along local -Z axis
        samples = [
            make_fixed_matrix((0.0, -10.0, -i * 0.1))
            for i in range(30)
        ]
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "pedestal-down")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_pan_left(self):
        # Stationary position, yaw turning left
        pos = (0.0, -10.0, 0.0)
        samples = []
        for i in range(30):
            # Target moves left along -X
            angle = -0.02 * i
            forward = (math.sin(angle), math.cos(angle), 0.0)
            samples.append(make_fixed_matrix(pos, forward=forward))
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "pan-left")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_pan_right(self):
        # Stationary position, yaw turning right
        pos = (0.0, -10.0, 0.0)
        samples = []
        for i in range(30):
            angle = 0.02 * i
            forward = (math.sin(angle), math.cos(angle), 0.0)
            samples.append(make_fixed_matrix(pos, forward=forward))
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "pan-right")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_tilt_up(self):
        # Stationary position, pitch turning up (+Z)
        pos = (0.0, -10.0, 0.0)
        samples = []
        for i in range(30):
            angle = 0.02 * i
            forward = (0.0, math.cos(angle), math.sin(angle))
            samples.append(make_fixed_matrix(pos, forward=forward))
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "tilt-up")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_tilt_down(self):
        # Stationary position, pitch turning down (-Z)
        pos = (0.0, -10.0, 0.0)
        samples = []
        for i in range(30):
            angle = -0.02 * i
            forward = (0.0, math.cos(angle), math.sin(angle))
            samples.append(make_fixed_matrix(pos, forward=forward))
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "tilt-down")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_orbit_right(self):
        # Circling target (0,0,0) in XY plane, moving right
        target = (0.0, 0.0, 0.0)
        radius = 10.0
        samples = []
        # Starts at (0, -10, 0), angle sweeps towards (+X)
        for i in range(30):
            angle = -math.pi / 2.0 + i * 0.03
            pos = (radius * math.cos(angle), radius * math.sin(angle), 0.0)
            samples.append(make_look_at_matrix(pos, target))
        res = classify(samples, self.fps, target=target)
        self.assertEqual(res["movement"], "orbit-right")
        self.assertGreaterEqual(res["confidence"], 0.75)

    def test_orbit_left(self):
        # Circling target (0,0,0) in XY plane, moving left
        target = (0.0, 0.0, 0.0)
        radius = 10.0
        samples = []
        for i in range(30):
            angle = -math.pi / 2.0 - i * 0.03
            pos = (radius * math.cos(angle), radius * math.sin(angle), 0.0)
            samples.append(make_look_at_matrix(pos, target))
        res = classify(samples, self.fps, target=target)
        self.assertEqual(res["movement"], "orbit-left")
        self.assertGreaterEqual(res["confidence"], 0.75)

    def test_zoom_in(self):
        samples = [make_fixed_matrix((0.0, -10.0, 0.0)) for _ in range(30)]
        lens_samples = [35.0 + i * 1.5 for i in range(30)]
        res = classify(samples, self.fps, lens_samples=lens_samples)
        self.assertEqual(res["movement"], "zoom-in")
        self.assertGreaterEqual(res["confidence"], 0.85)

    def test_zoom_out(self):
        samples = [make_fixed_matrix((0.0, -10.0, 0.0)) for _ in range(30)]
        lens_samples = [85.0 - i * 1.5 for i in range(30)]
        res = classify(samples, self.fps, lens_samples=lens_samples)
        self.assertEqual(res["movement"], "zoom-out")
        self.assertGreaterEqual(res["confidence"], 0.85)

    def test_dolly_zoom(self):
        # Dolly-in (forward along +Y) while zooming out (lens mm decreasing)
        samples = [
            make_fixed_matrix((0.0, -10.0 + i * 0.1, 0.0))
            for i in range(30)
        ]
        lens_samples = [70.0 - i * 1.0 for i in range(30)]
        res = classify(samples, self.fps, lens_samples=lens_samples)
        self.assertEqual(res["movement"], "dolly-zoom")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_dolly_zoom_out_zoom_in(self):
        # Dolly-out (backward along -Y) while zooming in (lens mm increasing)
        samples = [
            make_fixed_matrix((0.0, -10.0 - i * 0.1, 0.0))
            for i in range(30)
        ]
        lens_samples = [35.0 + i * 1.0 for i in range(30)]
        res = classify(samples, self.fps, lens_samples=lens_samples)
        self.assertEqual(res["movement"], "dolly-zoom")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_orbit_without_explicit_target(self):
        # Orbit inferred from camera movement and heading
        radius = 10.0
        samples = []
        for i in range(30):
            angle = -math.pi / 2.0 + i * 0.03
            pos = (radius * math.cos(angle), radius * math.sin(angle), 0.0)
            samples.append(make_look_at_matrix(pos, (0.0, 0.0, 0.0)))
        res = classify(samples, self.fps, target=None)
        self.assertEqual(res["movement"], "orbit-right")

    def test_noise_tolerance_pan(self):
        # Pan with small noise
        rng = random.Random(999)
        pos = (0.0, -10.0, 0.0)
        samples = []
        for i in range(30):
            angle = 0.03 * i + (rng.random() - 0.5) * 0.005
            forward = (math.sin(angle), math.cos(angle), 0.0)
            samples.append(make_fixed_matrix(pos, forward=forward))
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "pan-right")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_row_vector_matrix(self):
        # Matrix transposed (DirectX row-vector style where row 3 is translation)
        samples = []
        for i in range(30):
            m = make_fixed_matrix((0.0, -10.0 + i * 0.1, 0.0))
            # Transpose m
            m_transposed = [[m[c][r] for c in range(4)] for r in range(4)]
            samples.append(m_transposed)
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "dolly-in")

    def test_handheld(self):
        # Alternating high-frequency jitter with small net change
        rng = random.Random(42)
        samples = []
        for i in range(40):
            jx = (1 if i % 2 == 0 else -1) * 0.05 + (rng.random() - 0.5) * 0.02
            jy = (1 if (i // 2) % 2 == 0 else -1) * 0.05 + (rng.random() - 0.5) * 0.02
            jz = (1 if (i // 3) % 2 == 0 else -1) * 0.05 + (rng.random() - 0.5) * 0.02
            pos = (jx, -10.0 + jy, jz)
            forward = (jx * 0.1, 1.0, jz * 0.1)
            samples.append(make_fixed_matrix(pos, forward=forward))
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "handheld")

    def test_noise_tolerance_dolly(self):
        # Dolly-in with random jitter added
        rng = random.Random(123)
        samples = []
        for i in range(30):
            nx = (rng.random() - 0.5) * 0.01
            ny = (rng.random() - 0.5) * 0.01
            nz = (rng.random() - 0.5) * 0.01
            pos = (nx, -10.0 + i * 0.15 + ny, nz)
            samples.append(make_fixed_matrix(pos))
        res = classify(samples, self.fps)
        self.assertEqual(res["movement"], "dolly-in")
        self.assertGreaterEqual(res["confidence"], 0.8)

    def test_speed_classification(self):
        # Slow dolly
        slow_samples = [make_fixed_matrix((0.0, -10.0 + i * 0.01, 0.0)) for i in range(30)]
        res_slow = classify(slow_samples, self.fps)
        self.assertEqual(res_slow["speed"], "slow")

        # Fast dolly
        fast_samples = [make_fixed_matrix((0.0, -10.0 + i * 0.5, 0.0)) for i in range(30)]
        res_fast = classify(fast_samples, self.fps)
        self.assertEqual(res_fast["speed"], "fast")

    def test_dict_input_with_target(self):
        target = [0.0, 0.0, 0.0]
        radius = 10.0
        matrices = []
        for i in range(30):
            angle = -math.pi / 2.0 + i * 0.03
            pos = (radius * math.cos(angle), radius * math.sin(angle), 0.0)
            matrices.append(make_look_at_matrix(pos, target))
        payload = {"matrices": matrices, "target": target}
        res = classify(payload, self.fps)
        self.assertEqual(res["movement"], "orbit-right")

    def test_empty_or_single_sample(self):
        res_empty = classify([], self.fps)
        self.assertEqual(res_empty["movement"], "static")

        single = [make_fixed_matrix((0.0, 0.0, 0.0))]
        res_single = classify(single, self.fps)
        self.assertEqual(res_single["movement"], "static")


if __name__ == "__main__":
    unittest.main()
