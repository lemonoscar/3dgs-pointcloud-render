"""Display-only rotation: do not modify original Gaussian quaternions."""
import numpy as np


def rotation_x(degrees):
    c, s = np.cos(np.deg2rad(degrees)), np.sin(np.deg2rad(degrees))
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype='f4')
