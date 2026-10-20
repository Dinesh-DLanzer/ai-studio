"""Camera motion classifier.

Decomposes frame-by-frame 4x4 camera world matrices (and optional lens samples / target)
into standard cinematic camera movement classes:
  static, pan-left, pan-right, tilt-up, tilt-down,
  dolly-in, dolly-out, truck-left, truck-right, pedestal-up, pedestal-down,
  orbit-left, orbit-right, zoom-in, zoom-out, dolly-zoom, handheld.
"""
from __future__ import annotations

import math
from typing import Any, Sequence


def _vec_len(v: Sequence[float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _vec_sub(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _vec_dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec_cross(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _vec_norm(v: Sequence[float]) -> list[float]:
    length = _vec_len(v)
    if length < 1e-9:
        return [0.0, 0.0, 0.0]
    return [v[0] / length, v[1] / length, v[2] / length]


def _extract_frame(m: Sequence[Sequence[float]]) -> tuple[list[float], list[float], list[float], list[float]]:
    """Extract position, right, up, forward vectors from a 4x4 row-major matrix.

    Handles standard column-vector form (Blender / OpenGL) and row-vector form.
    """
    # Detect row-vector vs column-vector convention:
    # In standard column-vector form: M[0..2][3] is translation, M[3] is [0, 0, 0, 1].
    # In row-vector form: M[3][0..2] is translation, col 3 is [0, 0, 0, 1]^T.
    is_row_vector = (
        abs(m[3][0]) + abs(m[3][1]) + abs(m[3][2]) > 1e-6
        and abs(m[0][3]) + abs(m[1][3]) + abs(m[2][3]) < 1e-6
    )

    if is_row_vector:
        pos = [float(m[3][0]), float(m[3][1]), float(m[3][2])]
        r_vec = [float(m[0][0]), float(m[0][1]), float(m[0][2])]
        u_vec = [float(m[1][0]), float(m[1][1]), float(m[1][2])]
        z_vec = [float(m[2][0]), float(m[2][1]), float(m[2][2])]
    else:
        pos = [float(m[0][3]), float(m[1][3]), float(m[2][3])]
        r_vec = [float(m[0][0]), float(m[1][0]), float(m[2][0])]
        u_vec = [float(m[0][1]), float(m[1][1]), float(m[2][1])]
        z_vec = [float(m[0][2]), float(m[1][2]), float(m[2][2])]

    r_norm = _vec_norm(r_vec)
    u_norm = _vec_norm(u_vec)

    # In Blender/OpenGL cameras, camera looks down -Z (Z points backward), so F = -Z.
    # Check orientation of R x U against Z vector.
    rxu = _vec_cross(r_norm, u_norm)
    if _vec_dot(rxu, z_vec) > 0.0:
        # Z points in the same direction as R x U (backward in right-handed convention)
        f_norm = [-z_vec[0], -z_vec[1], -z_vec[2]]
    else:
        f_norm = [z_vec[0], z_vec[1], z_vec[2]]

    f_norm = _vec_norm(f_norm)
    return pos, r_norm, u_norm, f_norm


def _count_sign_flips(values: list[float], threshold: float = 1e-4) -> tuple[int, int]:
    """Count how many times consecutive non-negligible values change sign."""
    flips = 0
    total = 0
    last_sign = 0
    for v in values:
        if abs(v) > threshold:
            s = 1 if v > 0 else -1
            if last_sign != 0:
                total += 1
                if s != last_sign:
                    flips += 1
            last_sign = s
    return flips, total


def classify(
    samples: Any,
    fps: float = 24.0,
    lens_samples: Sequence[float] | None = None,
    target: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Classify camera movement from camera world matrices and optional lens data.

    Args:
        samples: List of 4x4 nested lists (row-major world matrix per frame),
                 or a dict containing {"matrices": ..., "target": ...}.
        fps: Frames per second.
        lens_samples: Optional list of focal lengths in mm per frame.
        target: Optional 3D point (x, y, z) camera orbits around.

    Returns:
        dict with keys "movement", "speed", "confidence", "evidence".
    """
    if isinstance(samples, dict):
        matrix_list = (
            samples.get("matrices")
            or samples.get("samples")
            or samples.get("camera_matrices")
            or []
        )
        if target is None:
            target = samples.get("target") or samples.get("target_point")
        if lens_samples is None:
            lens_samples = samples.get("lens_samples") or samples.get("lens")
    else:
        matrix_list = samples or []

    num_samples = len(matrix_list)
    if num_samples < 2:
        return {
            "movement": "static",
            "speed": "slow",
            "confidence": 1.0,
            "evidence": {
                "duration_sec": 0.0,
                "sample_count": num_samples,
                "total_distance": 0.0,
                "net_distance": 0.0,
            },
        }

    # Extract frame states
    positions: list[list[float]] = []
    rights: list[list[float]] = []
    ups: list[list[float]] = []
    forwards: list[list[float]] = []

    for m in matrix_list:
        p, r, u, f = _extract_frame(m)
        positions.append(p)
        rights.append(r)
        ups.append(u)
        forwards.append(f)

    duration = max((num_samples - 1) / float(fps), 1e-4)

    # Frame-to-frame deltas
    dolly_steps: list[float] = []
    truck_steps: list[float] = []
    pedestal_steps: list[float] = []
    pan_steps: list[float] = []
    tilt_steps: list[float] = []
    roll_steps: list[float] = []
    step_dists: list[float] = []

    for i in range(num_samples - 1):
        dp = _vec_sub(positions[i + 1], positions[i])
        step_dists.append(_vec_len(dp))

        # Local coordinate translation at step i
        dolly_steps.append(_vec_dot(dp, forwards[i]))
        truck_steps.append(_vec_dot(dp, rights[i]))
        pedestal_steps.append(_vec_dot(dp, ups[i]))

        # Rotation angles (pan, tilt, roll)
        # Pan: yaw around Up axis (turning right = positive, turning left = negative)
        f_next = forwards[i + 1]
        f_curr = forwards[i]
        r_curr = rights[i]
        u_curr = ups[i]

        pan_angle = math.atan2(_vec_dot(f_next, r_curr), _vec_dot(f_next, f_curr))
        pan_steps.append(pan_angle)

        # Tilt: pitch around Right axis (turning up = positive, turning down = negative)
        tilt_angle = math.atan2(_vec_dot(f_next, u_curr), _vec_dot(f_next, f_curr))
        tilt_steps.append(tilt_angle)

        # Roll: rotation around Forward axis
        u_next = ups[i + 1]
        roll_angle = math.atan2(_vec_dot(u_next, r_curr), _vec_dot(u_next, u_curr))
        roll_steps.append(roll_angle)

    total_distance = sum(step_dists)
    net_dp = _vec_sub(positions[-1], positions[0])
    net_distance = _vec_len(net_dp)

    net_dolly = sum(dolly_steps)
    net_truck = sum(truck_steps)
    net_pedestal = sum(pedestal_steps)

    net_pan = sum(pan_steps)
    net_tilt = sum(tilt_steps)
    net_roll = sum(roll_steps)

    abs_pan = sum(abs(p) for p in pan_steps)
    abs_tilt = sum(abs(t) for t in tilt_steps)
    total_rot = sum(
        math.sqrt(p * p + t * t + r * r)
        for p, t, r in zip(pan_steps, tilt_steps, roll_steps)
    )

    # Lens changes
    has_lens = lens_samples is not None and len(lens_samples) >= 2
    lens_delta = (
        float(lens_samples[-1]) - float(lens_samples[0]) if has_lens else 0.0
    )
    lens_abs_change = (
        sum(abs(float(lens_samples[i + 1]) - float(lens_samples[i])) for i in range(len(lens_samples) - 1))
        if has_lens
        else 0.0
    )

    # Handheld / jitter metrics
    flips_d, total_d = _count_sign_flips(dolly_steps)
    flips_t, total_t = _count_sign_flips(truck_steps)
    flips_p, total_p = _count_sign_flips(pedestal_steps)
    flips_pan, total_pan = _count_sign_flips(pan_steps, threshold=1e-3)
    flips_tilt, total_tilt = _count_sign_flips(tilt_steps, threshold=1e-3)

    total_checks = total_d + total_t + total_p + total_pan + total_tilt
    total_flips = flips_d + flips_t + flips_p + flips_pan + flips_tilt
    flips_ratio = (total_flips / total_checks) if total_checks > 0 else 0.0

    evidence: dict[str, Any] = {
        "duration_sec": round(duration, 3),
        "total_distance": round(total_distance, 4),
        "net_distance": round(net_distance, 4),
        "dolly_net": round(net_dolly, 4),
        "truck_net": round(net_truck, 4),
        "pedestal_net": round(net_pedestal, 4),
        "pan_deg": round(net_pan * 180.0 / math.pi, 2),
        "tilt_deg": round(net_tilt * 180.0 / math.pi, 2),
        "roll_deg": round(net_roll * 180.0 / math.pi, 2),
        "total_rot_deg": round(total_rot * 180.0 / math.pi, 2),
        "lens_delta": round(lens_delta, 2) if has_lens else None,
        "sign_flips_ratio": round(flips_ratio, 3),
    }

    # Classification logic
    movement = "static"
    confidence = 0.9
    speed = "slow"

    # 1. Static check
    is_static = (
        total_distance < 0.05
        and total_rot < 0.03
        and (not has_lens or lens_abs_change < 1.0)
    )

    if is_static:
        movement = "static"
        speed = "slow"
        confidence = 1.0
        return {
            "movement": movement,
            "speed": speed,
            "confidence": confidence,
            "evidence": evidence,
        }

    # 2. Handheld check: high frequency oscillation / reversals without large net progress
    is_handheld = (
        flips_ratio > 0.35
        and (
            (total_distance > 0.05 and (net_distance / max(total_distance, 1e-6)) < 0.35)
            or (total_rot > 0.03 and (abs(net_pan) + abs(net_tilt)) / max(total_rot, 1e-6) < 0.35)
        )
    )
    if is_handheld:
        movement = "handheld"
        confidence = min(0.95, 0.6 + flips_ratio * 0.4)
        speed = "normal" if total_distance / duration > 0.5 else "slow"
        return {
            "movement": movement,
            "speed": speed,
            "confidence": round(confidence, 2),
            "evidence": evidence,
        }

    # 3. Dolly-Zoom check: forward/backward translation opposes lens change
    # Dolly in (net_dolly > 0) + Zoom out (lens_delta < 0), OR
    # Dolly out (net_dolly < 0) + Zoom in (lens_delta > 0)
    if has_lens and abs(lens_delta) > 2.0 and abs(net_dolly) > 0.15:
        if (net_dolly > 0 and lens_delta < 0) or (net_dolly < 0 and lens_delta > 0):
            movement = "dolly-zoom"
            confidence = 0.90
            speed_val = (abs(net_dolly) + abs(lens_delta) * 0.05) / duration
            speed = "fast" if speed_val > 1.5 else ("slow" if speed_val < 0.4 else "normal")
            return {
                "movement": movement,
                "speed": speed,
                "confidence": round(confidence, 2),
                "evidence": evidence,
            }

    # 4. Zoom check: lens changes dominate
    if has_lens and abs(lens_delta) > 2.0 and (total_distance < 0.15 or abs(lens_delta) > 5.0 * total_distance):
        movement = "zoom-in" if lens_delta > 0 else "zoom-out"
        confidence = 0.92
        zoom_speed = abs(lens_delta) / duration
        speed = "fast" if zoom_speed > 25.0 else ("slow" if zoom_speed < 8.0 else "normal")
        return {
            "movement": movement,
            "speed": speed,
            "confidence": round(confidence, 2),
            "evidence": evidence,
        }

    # 5. Orbit check: translation circles a target while camera keeps looking at it
    # Check if target is given or can be inferred
    target_candidate = list(target) if target is not None else None
    if target_candidate is None:
        # Check if lateral motion (truck) and yaw (pan) oppose each other as in orbit
        if abs(net_truck) > 0.3 and abs(net_pan) > 0.15 and (net_truck * net_pan < 0):
            est_radius = abs(net_truck) / abs(net_pan)
            target_candidate = [
                positions[0][j] + forwards[0][j] * est_radius for j in range(3)
            ]

    if target_candidate is not None:
        dists = [_vec_len(_vec_sub(target_candidate, p)) for p in positions]
        mean_dist = sum(dists) / len(dists)
        dist_var = (max(dists) - min(dists)) / max(mean_dist, 1e-6)

        # Alignments: how well forward vector points to target
        alignments = []
        for p, f in zip(positions, forwards):
            to_target = _vec_norm(_vec_sub(target_candidate, p))
            alignments.append(_vec_dot(f, to_target))
        mean_align = sum(alignments) / len(alignments)

        evidence["target_alignment"] = round(mean_align, 3)
        evidence["orbit_dist_variance"] = round(dist_var, 3)

        if mean_align > 0.80 and dist_var < 0.35 and abs(net_truck) > 0.2:
            movement = "orbit-right" if net_truck > 0 else "orbit-left"
            confidence = round(min(0.98, max(0.6, mean_align * (1.0 - dist_var))), 2)
            orbit_speed = (total_distance / duration)
            speed = "fast" if orbit_speed > 2.0 else ("slow" if orbit_speed < 0.5 else "normal")
            return {
                "movement": movement,
                "speed": speed,
                "confidence": confidence,
                "evidence": evidence,
            }

    # 6. Directional movement: compare translation components and rotation components
    rot_energy = math.sqrt(net_pan * net_pan + net_tilt * net_tilt)
    trans_energy = max(abs(net_dolly), abs(net_truck), abs(net_pedestal))

    # Threshold for rotation dominance:
    # 0.08 rad is ~4.5 degrees. If rotation is significant and translation is small or secondary:
    is_rotation_dominant = rot_energy > 0.05 and (trans_energy < 0.15 or rot_energy > trans_energy * 0.8)

    if is_rotation_dominant:
        if abs(net_pan) >= abs(net_tilt):
            movement = "pan-right" if net_pan > 0 else "pan-left"
            confidence = min(0.98, 0.75 + (abs(net_pan) / max(total_rot, 1e-6)) * 0.23)
            rot_deg_sec = (abs(net_pan) * 180.0 / math.pi) / duration
            speed = "fast" if rot_deg_sec > 25.0 else ("slow" if rot_deg_sec < 6.0 else "normal")
        else:
            movement = "tilt-up" if net_tilt > 0 else "tilt-down"
            confidence = min(0.98, 0.75 + (abs(net_tilt) / max(total_rot, 1e-6)) * 0.23)
            rot_deg_sec = (abs(net_tilt) * 180.0 / math.pi) / duration
            speed = "fast" if rot_deg_sec > 25.0 else ("slow" if rot_deg_sec < 6.0 else "normal")
    else:
        # Translation dominant
        d_val = abs(net_dolly)
        t_val = abs(net_truck)
        p_val = abs(net_pedestal)

        if d_val >= t_val and d_val >= p_val:
            movement = "dolly-in" if net_dolly > 0 else "dolly-out"
            dominance = d_val / max(d_val + t_val + p_val, 1e-6)
            confidence = min(0.98, 0.75 + dominance * 0.23)
        elif t_val >= d_val and t_val >= p_val:
            movement = "truck-right" if net_truck > 0 else "truck-left"
            dominance = t_val / max(d_val + t_val + p_val, 1e-6)
            confidence = min(0.98, 0.75 + dominance * 0.23)
        else:
            movement = "pedestal-up" if net_pedestal > 0 else "pedestal-down"
            dominance = p_val / max(d_val + t_val + p_val, 1e-6)
            confidence = min(0.98, 0.75 + dominance * 0.23)

        trans_speed = total_distance / duration
        speed = "fast" if trans_speed > 2.0 else ("slow" if trans_speed < 0.5 else "normal")

    return {
        "movement": movement,
        "speed": speed,
        "confidence": round(confidence, 2),
        "evidence": evidence,
    }
