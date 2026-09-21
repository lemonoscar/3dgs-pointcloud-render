"""Generated geometry exercises route geometry and CLI without external assets."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from plyscene import camera, ply_io, trajectory
from plyscene.cli import main, resolve
from plyscene.transforms import rotation_x
from test_pipeline import fixture


class TrajectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rc = trajectory.config()
        self.c = resolve(camera.DEFAULTS, dict(width=160, height=120, ssaa=1,
                                               azimuth=0, elevation=45))

    def tearDown(self):
        self.temp.cleanup()

    def test_csv_contract_and_duplicate_handling(self):
        path = self.root/'route.csv'
        path.write_text(' z , x , y \n0,1,2\n0,1,2\n1,1,2\n')
        points, stats = trajectory.load(path)
        np.testing.assert_array_equal(points, [[1,2,0], [1,2,1]])
        self.assertEqual(stats['consecutive_duplicates_removed'], 1)
        for data in ('x,y,z\n1,2,3\n1,2,3\n', 'x,y,z\n1,2,3\n1,2,nan\n',
                     '1,2,3\n4,5,6\n', 'x,y,z\n1,2,3\n1,2\n'):
            path.write_text(data)
            with self.assertRaises(ValueError):
                trajectory.load(path)

    def test_near_wall_cutaway_reverses_with_camera(self):
        route = np.array([[0,0,.1], [0,2,.1]])
        points = np.array([[.6,1,1.2], [-.6,1,1.2], [.6,1,0], [-.6,1,0], [5,1,0]])
        keep = trajectory.crop_mask(points, route, self.rc, self.c, chunk_size=2)
        np.testing.assert_array_equal(keep, [False, True, True, True, False])
        reverse = trajectory.crop_mask(points, route, self.rc, self.c | dict(azimuth=180))
        np.testing.assert_array_equal(reverse, [True, False, True, True, False])

    def test_local_height_union_handles_multiple_levels_and_vertical_risers(self):
        route = np.array([[0,0,.1], [0,1,.1], [0,1,1.1], [0,2,1.1]])
        points = np.array([[0,.9,.5], [0,1.8,1], [0,1.8,3.5], [0,1,-1.]])
        np.testing.assert_array_equal(trajectory.crop_mask(points, route, self.rc, self.c),
                                      [True, True, False, False])
        # Two passages share XY but intermediate empty levels are not a huge bounding box.
        route = np.array([[0,0,.1], [0,2,.1], [5,2,4.1], [0,2,4.1], [0,0,4.1]])
        points = np.array([[0,0,0], [0,0,2.5], [0,0,4]])
        np.testing.assert_array_equal(trajectory.crop_mask(points, route, self.rc, self.c),
                                      [True, False, True])

    def test_display_rotation_applied_to_both_route_and_scene(self):
        route = np.array([[0,0,.1], [0,2,.1]])
        points = np.array([[.6,1,1.2], [-.6,1,1.2], [.6,1,0]])
        reference = trajectory.crop_mask(points, route, self.rc, self.c)
        r = rotation_x(270)
        actual = trajectory.crop_mask(points @ r, route @ r, self.rc, self.c | dict(rotate_x=270))
        np.testing.assert_array_equal(actual, reference)

    def test_frustums_on_polyline_and_vertical_orientation(self):
        route = np.array([[0.,0,0], [0,0,2], [1,0,3], [1,2,3]])
        frames = trajectory.frustums(route, self.rc, self.c)
        delta = np.diff(route, axis=0)
        for apex, corners in frames:
            u = np.clip(((apex-route[:-1])*delta).sum(1)/(delta*delta).sum(1), 0, 1)
            nearest = route[:-1]+u[:, None]*delta
            i = np.linalg.norm(nearest-apex, axis=1).argmin()
            np.testing.assert_allclose(nearest[i], apex, atol=1e-12)
            forward = delta[i]/np.linalg.norm(delta[i])
            np.testing.assert_allclose(corners.mean(0)-apex, self.rc['frustum_length']*forward, atol=1e-12)
            self.assertTrue(np.isfinite(corners).all())
            self.assertAlmostEqual(np.linalg.norm(corners[1]-corners[0]), self.rc['frustum_width'])
        extent = trajectory.framing_points(route, frames)
        cam = camera.make_camera(extent, self.c)
        uv, _ = camera.project(extent, cam)
        self.assertTrue(((uv >= 0) & (uv < [cam['width'],cam['height']])).all())
        self.assertEqual(trajectory.frustums(route, self.rc | dict(frustum_count=0), self.c), [])

    def test_simplification_preserves_corners_and_reversals(self):
        route = np.array([[0,0,0], [1,0,0], [2,0,0], [1,0,0], [1,0,1], [1,0,2]])
        np.testing.assert_array_equal(trajectory.vertices(route),
                                      [[0,0,0], [2,0,0], [1,0,0], [1,0,2]])

    def test_bad_config_and_misaligned_route(self):
        path = self.root/'config.json'
        for overrides in ({'radius': 0}, {'far_height': .1}, {'line_width': float('nan')},
                          {'frustum_count': 1.5}, {'frustum_count': True}, {'unknown': 1},
                          {'kind': 'planned'}, {'near_distance': 10}, {'route_color': '#ffff'}):
            path.write_text(json.dumps(overrides))
            with self.assertRaises(ValueError):
                trajectory.config(path)
        with self.assertRaises(ValueError):
            trajectory.crop_mask(np.zeros((2,3)), np.array([[50,50,50],[60,60,60]]), self.rc, self.c)

    def call(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            main(list(map(str, args)))
        return stream.getvalue()

    def test_cli_plan_crop_export_sampling_and_source_preservation(self):
        source = self.root/'input.ply'
        records = fixture(source)
        before = source.read_bytes()
        route = self.root/'route.csv'
        route.write_text('x,y,z\n0,0,.1\n0,2,.1\n')
        rc = self.root/'render.json'
        rc.write_text(json.dumps(self.c | dict(max_points=3)))
        output = self.root/'out.png'
        args = ('render', source, '--trajectory', route, '--config', rc, '--output', output)
        for backend in ('points', 'gaussian'):
            plan = json.loads(self.call(*args, '--backend', backend, '--plan'))
            self.assertEqual(plan['route_config']['kind'], 'illustrative')
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix('.crop.ply').exists())
        self.call(*args)
        metadata = json.loads(output.with_suffix('.json').read_text())
        self.assertEqual(metadata['counts']['rendered_points'], 3)
        self.assertEqual(metadata['counts']['after_route_crop'], 80)
        np.testing.assert_array_equal(ply_io.read(output.with_suffix('.crop.ply')), records[:80])
        self.assertEqual(source.read_bytes(), before)
        np.testing.assert_array_equal(trajectory.load(output.with_suffix('.trajectory.csv'))[0], [[0,0,.1],[0,2,.1]])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.call(*args)
        second = self.root/'reserved.png'
        second.with_suffix('.trajectory.csv').write_text('keep me')
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.call('render', source, '--trajectory', route, '--output', second, '--plan')
        self.assertFalse(second.exists())

    def test_route_config_without_trajectory_rejected(self):
        source = self.root/'input.ply'
        fixture(source)
        cfg = self.root/'route.json'
        cfg.write_text('{}')
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.call('render', source, '--route-config', cfg, '--output', self.root/'out.png', '--plan')


if __name__ == '__main__':
    unittest.main()
