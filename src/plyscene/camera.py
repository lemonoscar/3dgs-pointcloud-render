"""Shared orthographic camera, in source PLY coordinates."""
import numpy as np
from .transforms import rotation_x

DEFAULTS = dict(width=2400, height=1800, ssaa=2, azimuth=-55., elevation=50.,
                rotate_x=0., point_radius=1, shadow=0., tile=1024,
                max_points=0, min_opacity=0., bounds=None)

# A quality preset controls sampling and image resolution, not data filtering.
QUALITY = dict(full=dict(width=2400, height=1800, ssaa=2, max_points=0),
               preview=dict(width=1200, height=900, ssaa=1, max_points=500000))


def make_camera(points, c):
    a, e = np.deg2rad([c['azimuth'], c['elevation']])
    right = np.array([-np.sin(a), np.cos(a), 0])
    up = np.array([-np.sin(e)*np.cos(a), -np.sin(e)*np.sin(a), np.cos(e)])
    toward = np.cross(right, up)
    basis = (np.array([right, -up, toward]) @ rotation_x(c['rotate_x'])).T
    projected = points @ basis
    lo, hi = projected.min(0), projected.max(0)
    center = (lo + hi) / 2
    w, h = c['width']*c['ssaa'], c['height']*c['ssaa']
    scale = .78 * min(w/max(hi[0]-lo[0], 1e-6), h/max(hi[1]-lo[1], 1e-6))
    distance = max(float(np.linalg.norm(hi-lo))*2, 10.)
    view = np.eye(4, dtype='f4')
    view[:3, :3] = basis.T
    view[2, :3] *= -1
    view[:3, 3] = [-center[0], -center[1], distance+center[2]]
    intrinsics = np.array([[scale, 0, w/2], [0, scale, h*.46], [0, 0, 1]], dtype='f4')
    return dict(basis=basis, center=center, scale=scale, width=w, height=h,
                view=view, intrinsics=intrinsics, distance=distance)


def project(points, camera):
    p = points @ camera['basis']
    return (p[:, :2]-camera['center'][:2])*camera['scale'] + [camera['width']/2, camera['height']*.46], p[:, 2]
