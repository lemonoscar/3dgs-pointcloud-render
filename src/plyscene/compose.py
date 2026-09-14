"""White background and optional illustrative footprint shadow."""
import numpy as np
from PIL import Image, ImageFilter
from .camera import project
from .transforms import rotation_x


def finish(layer, points, camera, config):
    w, h = layer.size
    canvas = Image.new('RGBA', (w, h), 'white')
    if config['shadow']:
        rotation = rotation_x(config['rotate_x'])
        ground = points @ rotation.T
        ground[:, 2] = ground[:, 2].min() - np.ptp(ground[:, 2])*.06
        uv = np.rint(project(ground @ rotation, camera)[0]).astype('i8')
        ok = (uv[:, 0]>=0)&(uv[:, 0]<w)&(uv[:, 1]>=0)&(uv[:, 1]<h)
        mask = np.zeros((h, w), dtype='uint8')
        mask[uv[ok, 1], uv[ok, 0]] = 255
        # This is a synthetic presentation shadow, not physical ray tracing.
        shadow = Image.fromarray(mask).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(w*.013))
        shadow = shadow.point(lambda v: round(v*config['shadow']))
        shade = Image.new('RGBA', (w, h), (35, 38, 42, 0))
        shade.putalpha(shadow)
        canvas = Image.alpha_composite(canvas, shade)
    return Image.alpha_composite(canvas, layer).convert('RGB').resize(
        (config['width'], config['height']), Image.Resampling.LANCZOS)
