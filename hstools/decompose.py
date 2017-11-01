"""Decompose a surface into sht"""
from collections import namedtuple
from concurrent.futures import ProcessPoolExecutor, as_completed
import logging
from pathlib import Path
import numpy as np
from numpy.core.umath_tests import inner1d
import sbf
from scipy.spatial import cKDTree as KDTree, ConvexHull
from .sht import SHT
from .utils import spherical_to_cartesian

LOG = logging.getLogger('decompose')
Shape = namedtuple('Shape', 'name invariants')

def _interpolate(idxs, norms):
    return np.mean(norms[idxs])


def shift_to_origin(pts):
    """reoriginate a set of points to be centered about [0, 0, 0]

    Arguments:
    pts -- set of points to reoriginate
    """
    center = np.mean(pts, axis=0)
    return pts - center


def mean_radius(pts, reoriginate=False):
    """Calculate the mean radius (distance to origin) of a set
    of vertices

    Arguments:
    pts -- set of points to calculate the mean norm

    Keyword arguments:
    reoriginate -- shift the points to be centered about [0,0,0] first
    (default False)"""
    if reoriginate:
        pts = shift_to_origin(pts)
    d2 = pts[:, 0] ** 2 + pts[:, 1] ** 2 + pts[:, 2] ** 2
    norms = np.sqrt(d2)
    mean_norm = np.mean(norms)
    return mean_norm


def centroid(verts, faces):
    normals = np.cross(verts[faces[:,1]] - verts[faces[:,0]],
                       verts[faces[:,2]] - verts[faces[:,0]])
    volume = inner1d(verts[faces[:,0]], normals).sum() / 6
    centroid = np.sum(normals[:] * (
                          (verts[faces[:,0]] + verts[faces[:,1]])**2 +
                          (verts[faces[:,1]] + verts[faces[:,2]])**2 +
                          (verts[faces[:,2]] + verts[faces[:,0]])**2
                      ), axis=0)
    return centroid/(24 * 2 * volume)


def values_from_grid(vals, ix):
    """Get a set of values from a grid, and a set of indices"""
    res = np.array([_interpolate(idxs, vals) for idxs in ix])
    return res


def sht_isosurface(filename, l_max=20, prop='electric_potential'):
    """Given an SBF, describe the set of vertices and their esp using sht.
    Will scale the mesh to be of unit mean radius.

    Arguments:
    filename -- name of the SBF file containing a surface

    Keyword arguments:
    prop -- the name of the vertex property to describe in combination
    with the shape (or radius)

    """
    name = Path(filename).stem
    f = sbf.File(filename)
    f.read()
    pts = f['vertices'].data.transpose()
    faces = f['faces'].data.transpose() - 1

    LOG.debug('Loaded vertex data')
    center = np.mean(pts, axis=0)
    # shift to be centered about the origin
    pts -= center

    # this is faster for some reason than np.apply_along_axis
    norms = np.sqrt(pts[:, 0] ** 2 + pts[:, 1] ** 2 + pts[:, 2] ** 2)
    mean_norm = np.mean(norms)
    pts /= mean_norm
    norms /= mean_norm
    pts_normalized = pts / np.reshape(norms, (pts.shape[0], 1))
    LOG.debug('Normalized points')
    sht = SHT(l_max)
    grid = sht.grid
    grid_cartesian = spherical_to_cartesian(
            np.c_[np.ones(grid.shape[0]), grid[:, 1], grid[:, 0]])
    LOG.debug('Constructing tree')
    tree = KDTree(pts_normalized)
    LOG.debug('Done')
    LOG.debug('Interpolating values')
    nn = tree.query(grid_cartesian, 1)
    LOG.debug('Done')
    shape = values_from_grid(norms, nn[1])
    property_values =  values_from_grid(f[prop].data, nn[1])
    # normalize property to be in [0,1], keep track of min and range
    prop_min = np.min(property_values)
    prop_scale = np.abs(np.max(property_values) - np.min(property_values))
    property_values -= prop_min
    if prop_scale != 0:
        property_values /= prop_scale
    others = [mean_norm, prop_min, prop_scale]
    combined = np.zeros(property_values.shape, dtype=np.complex128)
    combined.real = shape
    combined.imag = property_values

    coefficients = sht.analyse(combined)
    return name, others, coefficients


def reconstruct_surface(coeffs, l_max=20, degree=131, color_min=0.0, color_scale=1.0):
    """Reconstruct the HS by distorting a spherical mesh, generated
    from a lebedev grid.

    Arguments:
    coeffs -- the set of spherical harmonic coefficients

    Keyword arguments:
    l_max -- maximum angular momenta to reconstruct to (default 20)
    degree -- grid degree to use (see lebedev grids)
    """
    sht = SHT(l_max)
    grid = sht.grid
    # grid[:, 0] goes from 0 -> 2 PI
    # grid[:, 1] goes from 0 -> PI
    rtp = np.c_[np.ones(grid.shape[0]), grid[:, 1], grid[:, 0]]
    verts = rtp.copy()
    colors = np.zeros(grid.shape[0])
    sphere = spherical_to_cartesian(rtp)
    radius = sht.synthesis(coeffs)
    verts[:, 0] = radius[:].real
    colors[:] = radius.imag * color_scale + color_min 
    verts = spherical_to_cartesian(verts)
    faces = ConvexHull(sphere).simplices
    return verts, faces, colors


def surface_description(sbf_file, prop='d_norm'):
    """Describe a shape/isosurface using spherical harmonics.
    Returns a Shape object, consisting of invariants and an
    identifier for this (based on the filename)

    Arguments:
    sbf_file -- filename or Path object locating a valid surface file

    Keyword Arguments:
    prop -- Additional property to use in description
    """
    LOG.debug('Describing surface with spherical harmonics')
    name, others, coeffs = sht_isosurface(sbf_file, prop=prop)
    invariants = make_invariants(coeffs)
    invariants = np.insert(invariants, 0, others)
    return Shape(name, invariants)


def make_invariants(coefficients):
    """Construct the 'N' type invariants from sht coefficients.
    If coefficients is of length n, the size of the result will be sqrt(n)

    Arguments:
    coefficients -- the set of spherical harmonic coefficients
    """
    size = int(np.sqrt(len(coefficients)))
    invariants = np.empty(shape=(size), dtype=np.float64)
    for i in range(0, size):
        l, u = i**2, (i+1)**2
        invariants[i] = np.sum(coefficients[l:u+1] *
                               np.conj(coefficients[l:u+1])).real
    return invariants


def main():
    """Read through all sbf files in a directory, writing
    numpy arrays of sht coefficients for each shape encountered.
    """
    import argparse
    import pickle
    import os
    from tqdm import tqdm
    parser = argparse.ArgumentParser()
    parser.add_argument('directory')
    parser.add_argument('-l', '--lmax', default=20, type=int,
                        help='Maximum angular momentum')
    parser.add_argument('--log-file', default=None,
                        help='Log to file instead of stdout')
    parser.add_argument('--suffix', '-s', default='-hs.sbf',
                        help='File suffix to find sbf files')
    parser.add_argument('--log-level', default='INFO',
                        help='Log level')
    parser.add_argument('--jobs', '-j', default=4, type=int,
                        help='Number of parallel jobs to run')
    parser.add_argument('--output-directory', '-o', default='.',
                        help='Directory to store output numpy arrays')
    args = parser.parse_args()
    if args.log_file:
        logging.basicConfig(filename=args.log_file, level=args.log_level)
    else:
        logging.basicConfig(level=args.log_level)
    LOG.info('Starting %s, output: %s', args.directory, args.output_directory)
    if not os.path.exists(args.output_directory):
        os.mkdir(args.output_directory)

    paths = list(Path(args.directory).glob('*'+args.suffix))
    num_paths = len(paths)
    LOG.info('%d paths to process', num_paths)
    shapes = []
    with ProcessPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(surface_description, str(path)) for path in paths]
        for f in tqdm(as_completed(futures), total=num_paths, desc='SHT', unit='file'):
            shapes.append(f.result())

    with Path(args.directory, 'shapes'+ args.suffix + '.bin').open('wb') as f:
        pickle.dump(shapes, f)
    LOG.info('Finished %s', args.directory)

if __name__ == '__main__':
    main()
