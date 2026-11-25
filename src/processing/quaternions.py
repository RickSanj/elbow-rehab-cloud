"""Vectorized quaternion helpers. Quaternions are [w, x, y, z]."""

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation


def normalize(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, dtype=float)
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def to_rotation(q: np.ndarray) -> Rotation:
    q = np.atleast_2d(np.asarray(q, dtype=float))
    return Rotation.from_quat(q[:, [1, 2, 3, 0]])


def from_rotation(rotation: Rotation) -> np.ndarray:
    xyzw = np.atleast_2d(rotation.as_quat())
    return xyzw[:, [3, 0, 1, 2]]


def to_matrices(q: np.ndarray) -> np.ndarray:
    return to_rotation(q).as_matrix()


def slerp(q0: np.ndarray, q1: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Spherical linear interpolation between rows of q0 and q1 at fractions u."""
    q0 = normalize(np.atleast_2d(q0))
    q1 = normalize(np.atleast_2d(q1))
    u = np.asarray(u, dtype=float).reshape(-1, 1)

    dot = np.sum(q0 * q1, axis=1, keepdims=True)
    q1 = np.where(dot < 0.0, -q1, q1)  # shortest path
    dot = np.abs(dot)

    theta = np.arccos(np.clip(dot, -1.0, 1.0))
    sin_theta = np.sin(theta)
    close = sin_theta < 1e-6
    safe_sin = np.where(close, 1.0, sin_theta)
    w0 = np.where(close, 1.0 - u, np.sin((1.0 - u) * theta) / safe_sin)
    w1 = np.where(close, u, np.sin(u * theta) / safe_sin)
    return normalize(w0 * q0 + w1 * q1)


def keep_heading(current: np.ndarray, tilt_only: np.ndarray) -> np.ndarray:
    """Roll/pitch from ``tilt_only`` combined with the yaw of ``current``.

    Used to re-initialize a filter from the accelerometer after a gap without
    discarding the heading (the relative heading of the two sensors matters
    for the elbow angles; resetting it to 0 would corrupt them).
    """
    yaw, _, _ = to_rotation(current).as_euler("ZYX")[0]
    _, pitch, roll = to_rotation(tilt_only).as_euler("ZYX")[0]
    return from_rotation(Rotation.from_euler("ZYX", [yaw, pitch, roll]))[0]
