"""Radius/SOR on exact points or voxel centroids, preserving original records."""
import numpy as np
from scipy.spatial import cKDTree

DEFAULTS = dict(mode='voxel', method='both', voxel=.08, radius=.24,
                min_neighbors=5, sor_k=20, sor_std_ratio=2., workers=4)


def inlier_mask(points, config):
    c = config
    finite = np.isfinite(points).all(1)
    selected = points[finite]
    if not len(selected):
        raise ValueError('No finite points')
    inverse = None
    if c['mode'] == 'voxel':
        # ponytail: proxy neighborhoods trade exact point-level decisions for memory savings.
        cells = np.floor((selected.astype('f8')-selected.min(0))/c['voxel'])
        if cells.max() >= np.iinfo(np.int64).max:
            raise ValueError('Voxel grid exceeds int64 range')
        _, inverse, counts = np.unique(cells.astype('i8'), axis=0, return_inverse=True, return_counts=True)
        representatives = np.column_stack([np.bincount(inverse, weights=selected[:, i])/counts for i in range(3)])
    else:
        representatives = selected
    n = len(representatives)
    use_sor = c['method'] in ('sor', 'both')
    use_radius = c['method'] in ('radius', 'both')
    if use_sor and n <= c['sor_k']:
        raise ValueError('Not enough points/occupied voxels for sor_k; reduce sor_k or voxel size')
    tree = cKDTree(representatives)
    distances, neighbors = np.zeros(n), np.zeros(n, dtype='i8')
    for start in range(0, n, 100000):
        batch = representatives[start:start+100000]
        if use_sor:
            d, _ = tree.query(batch, k=c['sor_k']+1, workers=c['workers'])
            distances[start:start+len(batch)] = d[:, 1:].mean(1)
        if use_radius:
            neighbors[start:start+len(batch)] = tree.query_ball_point(
                batch, c['radius'], return_length=True, workers=c['workers']) - 1
    threshold = float(distances.mean()+c['sor_std_ratio']*distances.std()) if use_sor else None
    radius_ok = neighbors >= c['min_neighbors'] if use_radius else np.ones(n, dtype=bool)
    sor_ok = distances <= threshold if use_sor else np.ones(n, dtype=bool)
    accepted = radius_ok & sor_ok
    keep = finite.copy()
    keep[finite] = accepted[inverse] if inverse is not None else accepted
    if not keep.any():
        raise ValueError('Denoising removed every point; check units and filter parameters')
    return keep, dict(source_points=len(points), finite_points=int(finite.sum()),
        retained_points=int(keep.sum()), removed_points=int((~keep).sum()),
        representatives=n, radius_rejected_representatives=int((~radius_ok).sum()),
        sor_rejected_representatives=int((~sor_ok).sum()), sor_threshold=threshold,
        combination='intersection of inliers on the same representative cloud',
        original_attributes_preserved=True)
