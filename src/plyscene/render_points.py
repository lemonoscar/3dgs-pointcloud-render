import numpy as np
from PIL import Image
from .camera import project
from .ply_io import colors


def raster(xy, depth, colors, width, height, radius):
    """Nearest point wins, including neighboring pixels covered by its disk."""
    uv = np.rint(xy).astype(int)
    zbuf = np.full(width * height, -np.inf, dtype='f4')
    result = np.zeros((width * height, 4), dtype='uint8')
    order = np.argsort(depth, kind='stable')
    uv, depth, colors = uv[order], depth[order], colors[order]
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            x, y = uv[:, 0] + dx, uv[:, 1] + dy
            ok = (x >= 0) & (x < width) & (y >= 0) & (y < height)
            ids, z, c = y[ok] * width + x[ok], depth[ok], colors[ok]
            # Make duplicate-pixel reduction explicit, not NumPy assignment-order dependent.
            _, reverse = np.unique(ids[::-1], return_index=True)
            nearest = len(ids)-1-reverse
            ids, z, c = ids[nearest], z[nearest], c[nearest]
            visible = z >= zbuf[ids]
            ids, z, c = ids[visible], z[visible], c[visible]
            zbuf[ids] = z
            result[ids, :3] = c
            result[ids, 3] = 255
    return Image.fromarray(result.reshape(height, width, 4))



def render(records, points, camera, config):
    xy, depth = project(points, camera)
    return raster(xy, depth, (colors(records)*255).astype('uint8'),
                  camera['width'], camera['height'], config['point_radius']*config['ssaa'])
