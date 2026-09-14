"""Small generated fixtures only: no scene data belongs in Git."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image
from plyscene import ply_io, camera, denoise, compose
from plyscene.cli import main, resolve, selection
from plyscene.render_gaussian import validate
from plyscene.render_points import raster


def fixture(path, gaussian=True):
    rng = np.random.default_rng(7)
    xyz = np.vstack([rng.normal(0, .02, (80, 3)), [8, 8, 8]])
    names = ['x', 'y', 'z']
    if gaussian:
        names += sorted(ply_io.GAUSSIAN_FIELDS) + ['f_rest_0', 'custom_value']
    records = np.zeros(len(xyz), dtype=[(n, '<f4') for n in names])
    for i, name in enumerate(('x', 'y', 'z')):
        records[name] = xyz[:, i]
    if gaussian:
        records['rot_0'] = 1
        records['opacity'] = 2
        records['custom_value'] = np.arange(len(records))
        records['f_rest_0'] = .42
        for i in range(3):
            records[f'scale_{i}'] = -4
    with path.open('wb') as stream:
        stream.write(('ply\nformat binary_little_endian 1.0\ncomment synthetic fixture\n'
                      f'element vertex {len(records)}\n'+''.join(f'property float {n}\n' for n in names)+'end_header\n').encode())
        records.tofile(stream)
    return records


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root/'input.ply'
        self.records = fixture(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            main(list(map(str, args)))
        return output.getvalue()

    def test_denoise_preserves_all_properties(self):
        for mode in ('voxel', 'exact'):
            config = resolve(denoise.DEFAULTS, dict(mode=mode, voxel=.001, radius=.2, sor_k=5))
            keep, stats = denoise.inlier_mask(ply_io.xyz(self.records), config)
            self.assertFalse(keep[-1])
            self.assertTrue(keep[:80].all())
            output = self.root/f'{mode}.ply'
            ply_io.write_selected(self.source, output, keep)
            result = ply_io.read(output)
            np.testing.assert_array_equal(result, self.records[keep])
            validate(result)
            with self.assertRaises(FileExistsError):
                ply_io.write_selected(self.source, output, keep)
        np.testing.assert_array_equal(ply_io.read(self.source), self.records)

    def test_individual_filters_and_invalid_parameters(self):
        for method in ('radius', 'sor', 'both'):
            keep, _ = denoise.inlier_mask(ply_io.xyz(self.records), resolve(denoise.DEFAULTS, dict(mode='exact', method=method)))
            self.assertFalse(keep[-1])
        for overrides in ({'voxel': 0}, {'sor_k': 2.5}, {'unknown': 1}, {'mode': 'bad'}):
            with self.assertRaises(ValueError):
                resolve(denoise.DEFAULTS, overrides)

    def test_selection_all_then_explicit_sample(self):
        c = resolve(camera.DEFAULTS, {})
        ids, _, stats = selection(self.records, c)
        self.assertEqual(len(ids), len(self.records))
        c.update(bounds=[-1, -1, -1, 1, 1, 1], max_points=7)
        ids, _, stats = selection(self.records, c)
        self.assertEqual(stats['selected_points'], 80)
        self.assertEqual(len(ids), 7)
        self.assertNotIn(80, ids)

    def test_camera_matches_gaussian_projection(self):
        points = ply_io.xyz(self.records)
        c = resolve(camera.DEFAULTS, dict(rotate_x=270, azimuth=170))
        cam = camera.make_camera(points, c)
        xy, depth = camera.project(points, cam)
        view_points = points @ cam['view'][:3, :3].T + cam['view'][:3, 3]
        expected = view_points[:, :2]*cam['scale'] + cam['intrinsics'][:2, 2]
        np.testing.assert_allclose(xy, expected, atol=.001)
        self.assertTrue((view_points[:, 2] > 0).all())
        self.assertAlmostEqual(np.linalg.det(cam['view'][:3, :3]), 1, places=5)

    def test_depth_and_disk(self):
        image = np.asarray(raster(np.array([[3, 3], [3, 3]]), np.array([1., 2.]),
                                  np.array([[255, 0, 0], [0, 255, 0]], dtype='u1'), 8, 8, 1))
        self.assertEqual(image[3, 3].tolist(), [0, 255, 0, 255])
        self.assertEqual(int((image[..., 3] > 0).sum()), 5)

    def test_cli_plan_render_report_and_overwrite(self):
        config = self.root/'config.json'
        config.write_text(json.dumps(dict(width=96, height=72, ssaa=1, shadow=.24)))
        output = self.root/'out.png'
        self.call('render', self.source, '--config', config, '--output', output, '--plan')
        self.assertFalse(output.exists())
        self.call('render', self.source, '--config', config, '--output', output)
        with Image.open(output) as image:
            self.assertEqual(image.size, (96, 72))
        metadata = json.loads(output.with_suffix('.json').read_text())
        self.assertEqual(metadata['counts']['rendered_points'], 81)
        self.assertEqual(metadata['input']['sha256'], ply_io.fingerprint(self.source)['sha256'])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.call('render', self.source, '--output', output)

    def test_plain_ply_rejected_only_by_gaussian(self):
        path = self.root/'plain.ply'
        fixture(path, gaussian=False)
        result = json.loads(self.call('inspect', path))
        self.assertFalse(result['gaussian'])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.call('render', path, '--backend', 'gaussian', '--output', self.root/'g.png', '--plan')

    def test_bad_ply_and_truncation(self):
        for text in (b'ply\nformat ascii 1.0\n', b'ply\nformat binary_little_endian 1.0\nelement face 1\n'):
            path = self.root/'bad.ply'
            path.write_bytes(text)
            with self.assertRaises(ValueError):
                ply_io.header(path)
        path.write_bytes(self.source.read_bytes()[:-1])
        with self.assertRaises(ValueError):
            ply_io.header(path)

    def test_cli_denoise_and_batch_without_grid(self):
        dc = self.root/'denoise.json'
        dc.write_text(json.dumps(dict(mode='exact')))
        clean = self.root/'clean.ply'
        self.call('denoise', self.source, '--config', dc, '--output', clean)
        self.assertEqual(ply_io.header(clean)[0], 80)
        manifest = self.root/'manifest.json'
        manifest.write_text(json.dumps(dict(schema_version=1, scenes=[dict(id='one', input='clean.ply', expected_source_points=80)])))
        config = self.root/'render.json'
        config.write_text(json.dumps(dict(width=96, height=72, ssaa=1)))
        self.call('batch', '--manifest', manifest, '--data-root', self.root,
                  '--config', config, '--output', self.root/'batch')
        self.assertEqual({p.name for p in (self.root/'batch').iterdir()}, {'one.png', 'one.json'})

    def test_quality_and_shadow_flags_both_backends(self):
        config = self.root/'quality.json'
        config.write_text(json.dumps(dict(width=100, height=80, ssaa=1, max_points=5, shadow=.5)))
        for backend in ('points', 'gaussian'):
            base = ('render', self.source, '--backend', backend, '--output', self.root/'plan.png', '--plan')
            default = json.loads(self.call(*base))['config']
            self.assertEqual(default['max_points'], 0)
            self.assertEqual(default['shadow'], 0)
            self.assertEqual(default['ssaa'], 2)
            preview = json.loads(self.call(*base, '--quality', 'preview', '--shadow'))['config']
            self.assertEqual(preview['max_points'], 500000)
            self.assertEqual(preview['shadow'], .24)
            full = json.loads(self.call(*base, '--config', config, '--quality', 'full',
                                       '--width', 3200, '--ssaa', 3, '--no-shadow'))['config']
            self.assertEqual(full['max_points'], 0)
            self.assertEqual(full['width'], 3200)
            self.assertEqual(full['ssaa'], 3)
            self.assertEqual(full['shadow'], 0)
            custom = json.loads(self.call(*base, '--max-points', 7, '--shadow', '.3'))['config']
            self.assertEqual(custom['max_points'], 7)
            self.assertEqual(custom['shadow'], .3)
        for flag, value in (('--shadow', '1.1'), ('--ssaa', '0'), ('--max-points', '-1')):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.call(*base, flag, value)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.call(*base, '--shadow', '--no-shadow')

    def test_shadow_compositor_optional(self):
        c = resolve(camera.DEFAULTS, dict(width=96, height=72, ssaa=1))
        points = ply_io.xyz(self.records)
        cam = camera.make_camera(points, c)
        layer = Image.new('RGBA', (96, 72), (0, 0, 0, 0))
        no_shadow = np.asarray(compose.finish(layer, points, cam, c))
        self.assertTrue((no_shadow == 255).all())
        c['shadow'] = .5
        shadow = np.asarray(compose.finish(layer, points, cam, c))
        self.assertTrue((shadow < no_shadow).any())

    def test_batch_cli_overrides_scene_quality_and_shadow(self):
        manifest = self.root/'manifest.json'
        manifest.write_text(json.dumps(dict(schema_version=1, scenes=[dict(id='one', input='input.ply',
            render=dict(max_points=3, shadow=.6, width=100))])))
        result = json.loads(self.call('batch', '--manifest', manifest, '--data-root', self.root,
            '--quality', 'full', '--max-points', 12, '--no-shadow', '--output', self.root/'batch', '--plan'))
        self.assertEqual(result['config']['max_points'], 12)
        self.assertEqual(result['config']['width'], 2400)
        self.assertEqual(result['config']['shadow'], 0)


if __name__ == '__main__':
    unittest.main()
