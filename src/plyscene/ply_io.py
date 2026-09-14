"""Strict binary scalar-vertex PLY I/O; never discard Gaussian attributes."""
import hashlib
import re
from pathlib import Path

import numpy as np

TYPES = dict(char='i1', uchar='u1', short='<i2', ushort='<u2', int='<i4',
             uint='<u4', float='<f4', double='<f8', int8='i1', uint8='u1',
             int16='<i2', uint16='<u2', int32='<i4', uint32='<u4',
             float32='<f4', float64='<f8')
GAUSSIAN_FIELDS = {*(f'scale_{i}' for i in range(3)),
                   *(f'rot_{i}' for i in range(4)), 'opacity',
                   *(f'f_dc_{i}' for i in range(3))}


def header(path):
    lines, fields, count, vertex = [], [], None, False
    with Path(path).open('rb') as stream:
        if stream.readline().strip() != b'ply':
            raise ValueError('Not a PLY file')
        lines.append(b'ply\n')
        while True:
            line = stream.readline(65537)
            if not line or len(line) > 65536 or sum(map(len, lines)) > 1048576:
                raise ValueError('Invalid or oversized PLY header')
            lines.append(line)
            words = line.decode('ascii').split()
            if not words:
                continue
            if words[0] == 'format' and words != ['format', 'binary_little_endian', '1.0']:
                raise ValueError('Export as binary_little_endian PLY 1.0 first')
            if words[0] == 'element':
                if len(words) != 3:
                    raise ValueError('Invalid element declaration')
                if words[1] != 'vertex' or count is not None:
                    raise ValueError('Only vertex-only point PLY is supported; mesh elements are rejected')
                count, vertex = int(words[2]), True
            elif words[0] == 'property':
                if not vertex or len(words) != 3 or words[1] not in TYPES:
                    raise ValueError('Only scalar vertex properties are supported')
                fields.append((words[2], TYPES[words[1]]))
            if words[0] == 'end_header':
                offset = stream.tell()
                break
    raw = b''.join(lines)
    if raw.splitlines().count(b'format binary_little_endian 1.0') != 1:
        raise ValueError('Missing or duplicate PLY format')
    dtype = np.dtype(fields)
    if count is None or count <= 0 or not {'x', 'y', 'z'} <= set(dtype.names):
        raise ValueError('PLY requires nonempty x/y/z vertices')
    if Path(path).stat().st_size != offset + count * dtype.itemsize:
        raise ValueError('PLY payload size differs from header; truncated or extra elements')
    return count, dtype, offset, raw


def read(path):
    n, dtype, offset, _ = header(path)
    return np.memmap(path, mode='r', dtype=dtype, offset=offset, shape=(n,))


def xyz(records):
    return np.column_stack([records[k] for k in ('x', 'y', 'z')]).astype('f4')


def colors(records):
    if {'red', 'green', 'blue'} <= set(records.dtype.names):
        rgb = np.column_stack([records[k] for k in ('red', 'green', 'blue')]).astype('f4')
        for i, k in enumerate(('red', 'green', 'blue')):
            if records.dtype[k].kind in 'ui':
                rgb[:, i] /= np.iinfo(records.dtype[k]).max
    elif {f'f_dc_{i}' for i in range(3)} <= set(records.dtype.names):
        rgb = .5 + .28209479177387814 * np.column_stack([records[f'f_dc_{i}'] for i in range(3)])
    else:
        rgb = np.full((len(records), 3), .65, dtype='f4')
    return np.clip(rgb, 0, 1)


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return dict(path=str(Path(path).resolve()), bytes=Path(path).stat().st_size,
                sha256=digest.hexdigest())


def write_selected(source, output, keep):
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError('Output cannot replace input')
    records = read(source)
    if keep.dtype != bool or keep.shape != (len(records),) or not keep.any():
        raise ValueError('Invalid mask or no surviving points')
    raw = re.sub(rb'element vertex \d+', f'element vertex {int(keep.sum())}'.encode(), header(source)[3])
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create: original and existing outputs are never overwritten.
    with output.open('xb') as stream:
        stream.write(raw)
        for start in range(0, len(records), 250000):
            records[start:start+250000][keep[start:start+250000]].tofile(stream)
