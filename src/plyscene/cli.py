"""Public commands: inspect, denoise, render, batch. No implicit data cleaning."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from . import __version__, ply_io, denoise, camera, compose


def config_file(path):
    value = json.loads(Path(path).read_text()) if path else {}
    if not isinstance(value, dict):
        raise ValueError('Config must be a JSON object')
    return value


def resolve(defaults, overrides):
    unknown = overrides.keys() - defaults.keys()
    if unknown:
        raise ValueError('Unknown config keys: '+', '.join(sorted(unknown)))
    result = defaults | overrides
    for k, default in defaults.items():
        value = result[k]
        if isinstance(default, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
                raise ValueError(f'{k} must be a finite number')
            if isinstance(default, int) and not isinstance(value, int):
                raise ValueError(f'{k} must be an integer')
    if 'method' in result:
        if result['mode'] not in ('exact', 'voxel') or result['method'] not in ('radius', 'sor', 'both'):
            raise ValueError('mode: exact/voxel; method: radius/sor/both')
        for k in ('voxel', 'radius', 'min_neighbors', 'sor_k', 'sor_std_ratio', 'workers'):
            if result[k] <= 0:
                raise ValueError(f'{k} must be positive')
    else:
        for k in ('width', 'height', 'ssaa', 'tile'):
            if result[k] <= 0:
                raise ValueError(f'{k} must be positive')
        if result['max_points'] < 0 or result['point_radius'] < 0:
            raise ValueError('max_points and point_radius must be nonnegative')
        if not 0 <= result['shadow'] <= 1 or not 0 <= result['min_opacity'] < 1:
            raise ValueError('shadow must be [0,1]; min_opacity must be [0,1)')
        if not 0 < result['elevation'] <= 90:
            raise ValueError('elevation must be (0,90]')
        if not 0 < result['framing'] <= .90:
            raise ValueError('framing must be (0,0.90] to leave space for annotations/shadows')
        if result['bounds'] is not None:
            b = np.asarray(result['bounds'], dtype=float)
            if b.shape != (6,) or not np.isfinite(b).all() or np.any(b[:3] > b[3:]):
                raise ValueError('bounds: [xmin,ymin,zmin,xmax,ymax,zmax] in source PLY coordinates')
    return result


def available(output, suffix):
    output = Path(output)
    if output.suffix.lower() != suffix:
        raise ValueError(f'Output must end in {suffix}')
    for path in (output, output.with_suffix('.json')):
        if path.exists():
            raise FileExistsError(f'Refusing to overwrite {path}; choose a new output')


def render_config(args, scene=None):
    overrides = config_file(args.config) | (scene or {})
    if getattr(args, 'trajectory', None):
        overrides.setdefault('elevation', 45.)
    # Explicit CLI choices override files; absent flags preserve scene settings.
    if args.quality is not None:
        overrides.update(camera.QUALITY[args.quality])
    for key in ('width', 'height', 'ssaa', 'max_points', 'point_radius', 'tile', 'shadow'):
        value = getattr(args, key)
        if value is not None:
            overrides[key] = value
    return resolve(camera.DEFAULTS, overrides)


def report(output, source, config, details):
    root = Path(__file__).resolve().parents[2]
    def git(*args):
        r = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    versions = {}
    for name in ('numpy', 'scipy', 'Pillow', 'torch', 'gsplat'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    metadata = dict(schema_version=1, toolkit_version=__version__,
        created_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        command=sys.argv, python=platform.python_version(), dependencies=versions,
        commit=git('rev-parse', 'HEAD'), git_status=git('status', '--porcelain'),
        input=ply_io.fingerprint(source), output=ply_io.fingerprint(output),
        config=config, **details)
    with Path(output).with_suffix('.json').open('x') as stream:
        json.dump(metadata, stream, indent=2)
        stream.write('\n')


def selection(records, config):
    points = ply_io.xyz(records)
    keep = np.isfinite(points).all(1)
    # Shared selection applies identically to both backends.
    for field in records.dtype.names:
        if records.dtype[field].kind == 'f':
            keep &= np.isfinite(records[field])
    finite = int(keep.sum())
    if config['min_opacity']:
        if 'opacity' not in records.dtype.names:
            raise ValueError('min_opacity requires Gaussian logit opacity field')
        t = config['min_opacity']
        keep &= records['opacity'] >= np.log(t/(1-t))
    visible = int(keep.sum())
    if config['bounds'] is not None:
        b = np.array(config['bounds'])
        keep &= ((points >= b[:3]) & (points <= b[3:])).all(1)
    ids = np.flatnonzero(keep)
    selected = len(ids)
    if not selected:
        raise ValueError('No points survive explicit selection')
    limit = config['max_points']
    if limit and len(ids) > limit:
        ids = ids[np.linspace(0, len(ids)-1, limit, dtype='i8')]
    return ids, points[ids], dict(source_points=len(records), finite_points=finite,
        after_opacity=visible, selected_points=selected, rendered_points=len(ids))


def render_one(source, output, backend, config, plan=False, expected=None,
               trajectory_path=None, route_config_path=None):
    n, dtype, _, _ = ply_io.header(source)
    if expected is not None and n != expected:
        raise ValueError(f'{source}: source count {n} differs from manifest {expected}')
    if backend == 'gaussian' and not ply_io.GAUSSIAN_FIELDS <= set(dtype.names):
        raise ValueError('Input lacks Gaussian attributes; use --backend points')
    available(output, '.png')
    route_details = {}
    if route_config_path and not trajectory_path:
        raise ValueError('--route-config requires --trajectory')
    if trajectory_path:
        from . import trajectory
        route, route_stats = trajectory.load(trajectory_path)
        rc = trajectory.config(route_config_path)
        output = Path(output)
        crop_output = output.with_suffix('.crop.ply')
        route_output = output.with_suffix('.trajectory.csv')
        for path in (crop_output, route_output):
            if path.exists():
                raise FileExistsError(f'Refusing to overwrite {path}; choose a new output')
        route_details = dict(trajectory=str(trajectory_path), route_config=rc,
                             crop_output=str(crop_output), trajectory_output=str(route_output), **route_stats)
    if plan:
        print(json.dumps(dict(input=str(source), source_points=n, backend=backend,
                              output=str(output), config=config, **route_details), indent=2))
        return
    start = time.monotonic()
    records = ply_io.read(source)
    # Sample only AFTER the full route corridor is selected. The exported crop
    # always contains all survivors, independent of preview sampling/backend.
    ids, points, counts = selection(records, config | {'max_points': 0} if trajectory_path else config)
    overlay = None
    if trajectory_path:
        keep = trajectory.crop_mask(points, route, rc, config)
        ids, points = ids[keep], points[keep]
        crop_keep = np.zeros(len(records), dtype=bool)
        crop_keep[ids] = True
        counts['after_route_crop'] = len(ids)
        frames = trajectory.frustums(route, rc, config)
        cam = camera.make_camera(np.vstack([points, trajectory.framing_points(route, frames)]), config)
        route_details.update(input=ply_io.fingerprint(trajectory_path), config=rc,
            length=float(np.linalg.norm(np.diff(route, axis=0), axis=1).sum()),
            route_rows=len(route), crop_segments=len(trajectory.vertices(route))-1,
            selected_indices_sha256=hashlib.sha256(ids.astype('<i8').tobytes()).hexdigest(),
            annotation='2D overlay; no depth occlusion or collision validation',
            frustums='Illustrative 3D path tangents, not measured camera orientations',
            frustum_apices=[p.tolist() for p, _ in frames],
            coordinates='Source PLY coordinates; rotate_x is display/crop frame only',
            crop='Union of local-height segment corridors; camera-facing near-side cutaway, not semantic segmentation')
        limit = config['max_points']
        if limit and len(ids) > limit:
            sample = np.linspace(0, len(ids)-1, limit, dtype='i8')
            ids, points = ids[sample], points[sample]
        counts['rendered_points'] = len(ids)
        overlay = lambda canvas: trajectory.draw(canvas, route, frames, cam, rc, config)
    else:
        cam = camera.make_camera(points, config)
    selected = records[ids]
    if backend == 'gaussian':
        from .render_gaussian import render
    else:
        from .render_points import render
    layer = render(selected, points, cam, config)
    image = compose.finish(layer, points, cam, config, overlay)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        image.save(stream, format='PNG', dpi=(300, 300))
    if trajectory_path:
        ply_io.write_selected(source, crop_output, crop_keep)
        with route_output.open('x') as stream:
            np.savetxt(stream, route, delimiter=',', header='x,y,z', comments='', fmt='%.17g')
        route_details['crop_file'] = ply_io.fingerprint(crop_output)
        route_details['normalized_trajectory'] = ply_io.fingerprint(route_output)
    report(output, source, config, dict(backend=backend, counts=counts,
        camera_view=cam['view'].tolist(), intrinsics=cam['intrinsics'].tolist(),
        color_mode='RGB or DC only; higher SH not evaluated',
        shadow='synthetic footprint' if config['shadow'] else 'none',
        **({'trajectory': route_details} if trajectory_path else {}),
        elapsed_seconds=time.monotonic()-start))
    print(f'{source}: {counts["rendered_points"]:,}/{n:,} points -> {output}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('inspect', help='Read header; --scan also reports finite XYZ bounds')
    p.add_argument('input', type=Path)
    p.add_argument('--scan', action='store_true')
    p = sub.add_parser('denoise', help='Write new PLY, preserving every vertex attribute')
    p.add_argument('input', type=Path)
    p.add_argument('--config', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--plan', action='store_true')
    for name in ('render', 'batch'):
        p = sub.add_parser(name, help='Render one PLY' if name == 'render' else 'Render independent images from a manifest')
        if name == 'render':
            p.add_argument('input', type=Path)
            p.add_argument('--trajectory', type=Path, help='Aligned XYZ CSV with x,y,z header; enables automatic route cutaway')
            p.add_argument('--route-config', type=Path, help='Route crop and annotation JSON; requires --trajectory')
        else:
            p.add_argument('--manifest', type=Path, required=True)
            p.add_argument('--data-root', type=Path, required=True)
            p.add_argument('--scene', help='Only render this scene ID')
        p.add_argument('--backend', choices=('points', 'gaussian'), default='points')
        p.add_argument('--config', type=Path)
        p.add_argument('--output', type=Path, required=True)
        p.add_argument('--plan', action='store_true', help='Header/config check only; no rendering')
        p.add_argument('--quality', choices=tuple(camera.QUALITY),
                       help='Preset: full (default settings, all selected points) or preview; explicit preset overrides config resolution/sampling')
        p.add_argument('--width', type=int, help='Final image width in pixels')
        p.add_argument('--height', type=int, help='Final image height in pixels')
        p.add_argument('--ssaa', type=int, help='Supersampling factor for both dimensions')
        p.add_argument('--max-points', type=int, help='0: all selected points/Gaussians; positive: explicit sampling limit')
        p.add_argument('--point-radius', type=int, help='Point backend: disk radius in final pixels')
        p.add_argument('--tile', type=int, help='Gaussian backend: tile edge in internal pixels (not a point limit)')
        shadow = p.add_mutually_exclusive_group()
        shadow.add_argument('--shadow', type=float, nargs='?', const=.24, metavar='STRENGTH',
                            help='Enable synthetic soft shadow; optional strength in [0,1], default 0.24')
        shadow.add_argument('--no-shadow', dest='shadow', action='store_const', const=0.,
                            help='Disable synthetic soft shadow, overriding config')
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect':
            n, dtype, _, _ = ply_io.header(args.input)
            result = dict(points=n, fields=list(dtype.names), gaussian=ply_io.GAUSSIAN_FIELDS <= set(dtype.names))
            if args.scan:
                points = ply_io.xyz(ply_io.read(args.input))
                finite = np.isfinite(points).all(1)
                result['finite_points'] = int(finite.sum())
                result['bounds'] = [points[finite].min(0).tolist(), points[finite].max(0).tolist()] if finite.any() else None
            print(json.dumps(result, indent=2))
        elif args.command == 'denoise':
            c = resolve(denoise.DEFAULTS, config_file(args.config))
            n = ply_io.header(args.input)[0]
            available(args.output, '.ply')
            if args.plan:
                print(json.dumps(dict(input=str(args.input), source_points=n, config=c, output=str(args.output)), indent=2))
                return
            keep, stats = denoise.inlier_mask(ply_io.xyz(ply_io.read(args.input)), c)
            ply_io.write_selected(args.input, args.output, keep)
            report(args.output, args.input, c, dict(operation='denoise', counts=stats))
            print(json.dumps(stats, indent=2))
        elif args.command == 'render':
            c = render_config(args)
            render_one(args.input, args.output, args.backend, c, args.plan,
                       trajectory_path=args.trajectory, route_config_path=args.route_config)
        else:
            manifest = config_file(args.manifest)
            if manifest.get('schema_version') != 1 or not isinstance(manifest.get('scenes'), list) or not manifest['scenes']:
                raise ValueError('Manifest requires schema_version=1 and nonempty scenes')
            scenes = manifest['scenes']
            ids = [s['id'] for s in scenes]
            if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i.replace('_', '').replace('-', '').isalnum() for i in ids):
                raise ValueError('Scene IDs must be unique safe names')
            if args.scene:
                scenes = [s for s in scenes if s['id'] == args.scene]
                if not scenes:
                    raise ValueError('Unknown scene ID')
            jobs = []
            for s in scenes:
                c = render_config(args, s.get('render', {}))
                source = (args.data_root / s['input']).resolve()
                if not source.is_relative_to(args.data_root.resolve()):
                    raise ValueError('Scene input must stay within data-root')
                output = args.output / (s['id']+'.png')
                jobs.append((source, output, c, s.get('expected_source_points')))
            # Preflight every job before starting expensive work.
            for source, output, c, expected in jobs:
                render_one(source, output, args.backend, c, True, expected)
            if args.plan:
                return
            for source, output, c, expected in jobs:
                render_one(source, output, args.backend, c, False, expected)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(2, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
