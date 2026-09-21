"""Trajectory-driven cutaways and illustrative 3D tangent frustums.

All public point arrays use source PLY coordinates. Only the crop calculation
uses the display's Z-up frame; exporting a crop never transforms attributes.
"""
import csv
import json
from pathlib import Path

import numpy as np
from PIL import ImageColor, ImageDraw, ImageFont

from .camera import project
from .transforms import rotation_x

DEFAULTS = dict(radius=1.65, floor_offset=.10, below=.25, near_height=.60,
                far_height=1.70, near_distance=.15, line_width=9.,
                frustum_count=12, frustum_length=.30, frustum_width=.225,
                frustum_height=.18, frustum_line_width=3.,
                route_color='#ff315b', frustum_color='#13bcb0',
                start_color='#08cbb0', end_color='#f02ac7', kind='illustrative')


def config(path=None):
    overrides = json.loads(Path(path).read_text()) if path else {}
    if not isinstance(overrides, dict) or overrides.keys() - DEFAULTS.keys():
        raise ValueError('Route config must be an object with known keys only')
    result = DEFAULTS | overrides
    for key, default in DEFAULTS.items():
        value = result[key]
        if isinstance(default, (float, int)):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not np.isfinite(value):
                raise ValueError(f'Route {key} must be a finite number')
            if value < 0:
                raise ValueError(f'Route {key} must be nonnegative')
        elif key.endswith('_color'):
            if not isinstance(value, str) or len(ImageColor.getrgb(value)) != 3:
                raise ValueError(f'Route {key} must be an RGB color')
    for key in ('radius', 'line_width', 'frustum_length', 'frustum_width',
                'frustum_height', 'frustum_line_width'):
        if result[key] <= 0:
            raise ValueError(f'Route {key} must be positive')
    if not isinstance(result['frustum_count'], int):
        raise ValueError('frustum_count must be an integer')
    if not result['near_height'] <= result['far_height']:
        raise ValueError('near_height must not exceed far_height')
    if result['near_distance'] > result['radius']:
        raise ValueError('near_distance must not exceed radius')
    if result['kind'] not in ('illustrative', 'recorded'):
        raise ValueError('Route kind must be illustrative or recorded (user supplied)')
    return result


def load(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.reader(stream)
        names = [name.strip() for name in next(reader, [])]
        if len(names) != 3 or set(names) != {'x', 'y', 'z'}:
            raise ValueError('Trajectory CSV requires exactly the header x,y,z')
        order = [names.index(n) for n in ('x', 'y', 'z')]
        rows = []
        for row in reader:
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) != 3:
                raise ValueError('Each trajectory row must contain three coordinates')
            rows.append([float(row[i]) for i in order])
    points = np.array(rows, dtype='f8')
    if points.ndim != 2 or len(points) < 2 or not np.isfinite(points).all():
        raise ValueError('Trajectory requires at least two finite XYZ rows')
    original = len(points)
    points = points[np.r_[True, np.any(np.diff(points, axis=0) != 0, axis=1)]]
    if len(points) < 2:
        raise ValueError('Trajectory must contain a nonzero segment')
    return points, dict(input_rows=original, consecutive_duplicates_removed=original-len(points))


def vertices(points):
    """Remove only collinear forward samples, retaining bends and reversals."""
    stack = []
    for p in points:
        while len(stack) >= 2:
            a, b = stack[-1]-stack[-2], p-stack[-1]
            if np.dot(a, b) <= 0 or np.linalg.norm(np.cross(a, b)) > 1e-10*np.linalg.norm(a)*np.linalg.norm(b):
                break
            stack.pop()
        stack.append(p)
    return np.asarray(stack)


def crop_mask(points, route, c, render_config, chunk_size=100000):
    """Union of segment corridors; each segment carries its own floor height.

    Horizontal distance locates sloping segments. A vertical segment uses its
    entire height interval, so stair risers and repeated XY are well defined.
    This is a camera-facing cutaway heuristic, not semantic wall recognition.
    """
    rotation = rotation_x(render_config['rotate_x'])
    path = vertices(route) @ rotation.T
    angle = np.deg2rad(render_config['azimuth'])
    toward_camera = np.array([np.cos(angle), np.sin(angle)])
    radius = c['radius']
    lo, hi = path.min(0), path.max(0)
    lo -= [radius, radius, c['floor_offset']+c['below']]
    hi += [radius, radius, c['far_height']-c['floor_offset']]
    result = np.zeros(len(points), dtype=bool)
    # ponytail: O(points * simplified segments); index segments if very long logs become costly.
    for start in range(0, len(points), chunk_size):
        q = points[start:start+chunk_size] @ rotation.T
        candidates = np.flatnonzero(((q >= lo) & (q <= hi)).all(1))
        q = q[candidates]
        keep = np.zeros(len(q), dtype=bool)
        for a, b in zip(path[:-1], path[1:]):
            delta = b-a
            horizontal_length2 = float(delta[:2] @ delta[:2])
            if horizontal_length2 > 1e-20:
                u = np.clip((q[:, :2]-a[:2]) @ delta[:2]/horizontal_length2, 0, 1)
                nearest = a + u[:, None]*delta
                low = high = nearest[:, 2]-c['floor_offset']
            else:
                nearest = np.broadcast_to(a, q.shape)
                low = min(a[2], b[2])-c['floor_offset']
                high = max(a[2], b[2])-c['floor_offset']
            lateral = q[:, :2]-nearest[:, :2]
            near = lateral @ toward_camera > c['near_distance']
            ceiling = high + np.where(near, c['near_height'], c['far_height'])
            keep |= ((lateral*lateral).sum(1) <= radius*radius) & (q[:, 2] >= low-c['below']) & (q[:, 2] <= ceiling)
        result[start+candidates[keep]] = True
    if not result.any():
        raise ValueError('No points near trajectory: check coordinates, units and route crop settings')
    return result


def frustums(route, c, render_config):
    """Equal-arc-length apices on the exact polyline, with full 3D tangents."""
    delta = np.diff(route, axis=0)
    length = np.linalg.norm(delta, axis=1)
    arc = np.r_[0., np.cumsum(length)]
    samples = np.linspace(0, arc[-1], c['frustum_count']+2)[1:-1]
    ids = np.minimum(np.searchsorted(arc, samples, side='right')-1, len(delta)-1)
    apices = route[ids] + ((samples-arc[ids])/length[ids])[:, None]*delta[ids]
    frames = []
    display_up = rotation_x(render_config['rotate_x']).T @ [0., 0., 1.]
    for p, i in zip(apices, ids):
        forward = delta[i]/length[i]
        reference = display_up
        if abs(forward @ reference) > .95:
            reference = np.eye(3)[np.argmin(abs(forward))]
        right = np.cross(forward, reference)
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        center = p + c['frustum_length']*forward
        corners = np.array([center + sx*c['frustum_width']/2*right + sy*c['frustum_height']/2*up
                            for sx, sy in ((-1,-1), (1,-1), (1,1), (-1,1))])
        frames.append((p, corners))
    return frames


def framing_points(route, frames):
    return np.vstack([route, *[corners for _, corners in frames]]) if frames else route


def draw(canvas, route, frames, cam, c, render_config):
    """Screen-space annotation, intentionally independent of scene occlusion."""
    painter = ImageDraw.Draw(canvas)
    ssaa = render_config['ssaa']
    pixels = lambda p: [tuple(v) for v in project(np.asarray(p), cam)[0]]
    painter.line(pixels(route), fill=c['route_color'], width=max(1, round(c['line_width']*ssaa)), joint='curve')
    for p, corners in frames:
        for corner in corners:
            painter.line(pixels([p, corner]), fill=c['frustum_color'], width=max(1, round(c['frustum_line_width']*ssaa)))
        painter.line(pixels(np.vstack([corners, corners[0]])), fill=c['frustum_color'],
                     width=max(1, round(c['frustum_line_width']*ssaa)), joint='curve')
    for p, color in ((route[0], c['start_color']), (route[-1], c['end_color'])):
        x, y = project(p[None], cam)[0][0]
        r = max(c['line_width']*.7, 4)*ssaa
        painter.ellipse((x-r, y-r, x+r, y+r), fill=color)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', max(10, round(render_config['width']*.009))*ssaa)
    except OSError:
        font = ImageFont.load_default()
    label = 'Illustrative trajectory' if c['kind'] == 'illustrative' else 'Recorded trajectory (user supplied)'
    painter.text((cam['width']/2, cam['height']-20*ssaa), label+' | Tangent frustums',
                 font=font, anchor='mm', fill='#777777')
