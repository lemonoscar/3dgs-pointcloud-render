"""Anisotropic gsplat renderer; optional CUDA imports are intentionally local."""
import numpy as np
from PIL import Image
from .ply_io import GAUSSIAN_FIELDS, colors


def validate(records):
    missing = GAUSSIAN_FIELDS - set(records.dtype.names)
    if missing:
        raise ValueError('Not a Gaussian PLY; missing fields: '+', '.join(sorted(missing)))
    for field in GAUSSIAN_FIELDS:
        if not np.isfinite(records[field]).all():
            raise ValueError(f'Nonfinite Gaussian attribute: {field}')
    if np.any(sum(records[f'rot_{i}'].astype('f8')**2 for i in range(4)) == 0):
        raise ValueError('Gaussian quaternion cannot be zero')


def render(records, points, camera, config):
    validate(records)
    try:
        import torch
        from gsplat.rendering import rasterization
    except ImportError as exc:
        raise RuntimeError('Gaussian backend needs CUDA PyTorch and pip install -e ".[gaussian]"') from exc
    if not torch.cuda.is_available():
        raise RuntimeError('Gaussian backend requires an NVIDIA CUDA GPU')
    scales = np.exp(np.column_stack([records[f'scale_{i}'] for i in range(3)]).astype('f4'))
    if not np.isfinite(scales).all() or np.any(scales <= 0):
        raise ValueError('Invalid Gaussian log-scales (overflow/underflow)')
    quats = np.column_stack([records[f'rot_{i}'] for i in range(4)]).astype('f4')
    quats /= np.linalg.norm(quats.astype('f8'), axis=1, keepdims=True)
    opacity = 1/(1+np.exp(-np.clip(records['opacity'].astype('f4'), -80, 80)))
    # v0.1 deliberately matches the previous DC-only renderer; higher SH stays in PLY.
    arrays = [torch.from_numpy(np.ascontiguousarray(a, dtype='f4')).cuda()
              for a in (points, quats, scales, opacity, colors(records))]
    w, h, tile = camera['width'], camera['height'], config['tile']
    rgba = np.zeros((h, w, 4), dtype='uint8')
    with torch.inference_mode():
        view = torch.from_numpy(camera['view'][None]).cuda()
        for y in range(0, h, tile):
            for x in range(0, w, tile):
                tw, th = min(tile, w-x), min(tile, h-y)
                k = camera['intrinsics'].copy()
                k[0, 2] -= x
                k[1, 2] -= y
                rgb, alpha, metadata = rasterization(*arrays, view, torch.from_numpy(k[None]).cuda(),
                    tw, th, camera_model='ortho', packed=True, radius_clip=0,
                    near_plane=.01, far_plane=camera['distance']*4,
                    rasterize_mode='antialiased', eps2d=.3)
                al = alpha[0].cpu().numpy()
                # gsplat returns premultiplied colors; Pillow expects straight RGBA.
                straight = np.divide(rgb[0].cpu().numpy(), al, out=np.zeros((th, tw, 3), dtype='f4'), where=al>0)
                rgba[y:y+th, x:x+tw, :3] = np.rint(np.clip(straight, 0, 1)*255).astype('u1')
                rgba[y:y+th, x:x+tw, 3] = np.rint(np.clip(al[..., 0], 0, 1)*255).astype('u1')
                del rgb, alpha, metadata
    return Image.fromarray(rgba)
