#!/usr/bin/python
# Core imports
from collections import defaultdict
from functools import reduce
from itertools import combinations
import concurrent.futures
import json
import time
# Library imports
from matplotlib import pyplot as plt
from scipy.cluster.hierarchy import dendrogram as dend
import fastcluster as fc
import numpy as np
import progressbar as pb
import scipy.cluster.hierarchy
import scipy.spatial.distance
import scipy.stats as stats
# Local imports
from . import data
from .data import log


def spearman_roc(histograms):
    """ Calculate the Spearman rank-order correlation coefficient from
    2 histograms This may need to be modified, I'm uncertain whether or
    not 2 zeroes are ignored READ likely that they aren't, as such
    artificially high correlations are probable"""
    H1, H2 = histograms
    try:
        hist1, _, _ = H1
        hist2, _, _ = H2
        x = hist1.flatten()
        y = hist2.flatten()

        r, p = stats.spearmanr(x, y)
        return r

    except ValueError as e:
        print('Error: {0}.'.format(e))
        print('Input must be a tuple of histograms.')
        return


def kendall_tau(histograms):
    """ Calculate Kendall's Tau from the given histograms. Significantly slower
    than Spearman ROC, and seems to produce slightly worse results."""
    try:
        H1, H2 = histograms
        hist1, _, _ = H1
        hist2, _, _ = H2
        x = hist1.flatten()
        y = hist2.flatten()
        r, p = stats.kendalltau(x, y)
        return r
    except ValueError as e:
        print('Error: {0}.'.format(e))
        print('Input must be a tuple of histograms.')
        return


def hdistance(histograms):
    """ Calculate a naive distance between two histograms"""
    try:
        H1, H2 = histograms
        hist1, _, _ = H1
        hist2, _, _ = H2
        x = hist1
        y = hist2
        dmat = x - y
        d = np.sum(dmat)
        return abs(d)

    except ValueError as e:
        print('Error: {0}.'.format(e))
        print('Input must be a tuple of histograms.')
        return


def dvalue(x):
    # unpack the tuple
    i1, i2 = x
    # Make NaNs zeroes
    i1[np.isnan(i1)] = 0
    i2[np.isnan(i2)] = 0
    # find all values where at LEAST one array is nonzero, and use these to
    # calculate distance
    ind1 = np.flatnonzero(i1)
    ind2 = np.flatnonzero(i2)
    ind = (np.union1d(ind1, ind2))
    # Euclidean distance
    d = np.power(np.sum(np.power(i2[ind] - i1[ind], 2)), 0.5)
    return d


def write_mat_file(fname, mat):
    np.savetxt(fname, mat, fmt="%.4e", delimiter=' ')


def get_dist_mat(values, test=spearman_roc, threads=8):
    """ Given a list of data, calculate the distances between them
        and return a NxN redundant array of these distances. """
    n = len(values)
    vals = []
    start_time = time.time()
    widgets = data.getWidgets('Calculating Matrix: ')

    log("""Creating {0}x{0} matrix,
        test={1}, using {2} threads""".format(n, test.__name__, threads))

    # Generating matrix will be O(exp(n)) time
    c = list(combinations(values, 2))
    numcalc = len(c)

    pbar = pb.ProgressBar(widgets=widgets, maxval=numcalc)
    pbar.start()

    i = 0
    # Parallel code
    with concurrent.futures.ThreadPoolExecutor(8) as executor:
        batch = c[i:i+100]
        while batch:
            for val in executor.map(test, batch, timeout=30):
                vals.append(val)
                i += 1
                pbar.update(i)
            batch = c[i:i+100]
    pbar.finish()

    vals = np.array(vals)
    mat = np.identity(n)
    """This step is key, basically we assign the upper triangle
      indices of a matrix size N, i.e.
      1    X    X    X
      0    1    X    X
      0    0    1    X
      0    0    0    1
      then we use the transpose of the matrix to copy the
      upper triangle into the lower triangle (making a
      symmetric matrix) """

    # Assign upper triangle
    try:
        mat[np.triu_indices(n, k=1)] = vals
    except ValueError as e:
        print("Error: {}".format(e))
        print("Couldn't broadcast array to triangle upper indices?")
        print("vals: {0}".format(vals))
        return

    # Make the matrix symmetric
    mat = (mat + mat.T) / 2

    # Because these tests give correlations not distances,
    # we must modify the values to give a distance equivalent
    if test is spearman_roc or test is kendall_tau:
        """ np.round() is used here because of floating point rounding
            (getting 1.0 - 1.0 != 0.0). Must perform this step to convert
            correlation data to distance """
        mat = 1.0 - np.round(mat, decimals=5)
        np.fill_diagonal(mat, 0.0)

    # Error checking for matrix to see if it is symmetric
    symmetry = np.allclose(mat.transpose(1, 0), mat)
    log("Matrix is symmetric: {0}".format(symmetry))
    if not symmetry:
        write_mat_file("mat1", mat)
        write_mat_file("mat2", mat.transpose(1, 0))

    t = time.time() - start_time
    output = 'Matrix took {0:.2}s to create. {1} pairwise calculations'

    log(output.format(t, numcalc))
    return mat


def cluster(mat, names, tname, dump=None,
            dendrogram=None, method=None,
            distance=None):
    """ Takes an NxN array of distances and an array of names with
      the same indices, performs cluster analysis and shows a dendrogram"""

    try:
        distArray = scipy.spatial.distance.squareform(mat)
    except ValueError as e:
        print(e)
        print(mat)
        return
    start_time = time.time()

    # This is the actual clustering using fastcluster
    Z = fc.linkage(distArray, method=method, metric=distance)
    log(Z)
    outstring = 'Clustering {0} data points'.format(len(names))
    outstring += ' took {0:.3}s'.format(time.time() - start_time)
    log(outstring)
    threshold = distance*max(Z[:, 2])
    if dendrogram:
        # Create a dendrogram
        dend(Z, labels=names, color_threshold=threshold)
        # Plot stuff
        plt.xlabel('Compound Name')
        plt.ylabel('Dissimilarity')
        dpi = 200
        plt.suptitle("""Clustering dendrogram of {0}
                    compounds using {1}""".format(len(names), tname))
        if len(names) > 100:
            fig = plt.gcf()
            fig.set_size_inches(10.5, min(len(names)*0.1, 32768/dpi))
        log('Saving dendrogram')
        plt.savefig(dendrogram, dpi=dpi)
        plt.close()
    dump = 'clusters.txt'
    if dump:
        log('Dumping tree structure in {0}'.format(dump))
        T = scipy.cluster.hierarchy.to_tree(Z, rd=False)
        d = dict(children=[], name="Root1")
        add_node(T, d)
        label_tree(d["children"][0], names)
        json.dump(d, open(dump, 'w'), sort_keys=True, indent=4)
        log('printing clusters')
        # HARDCODED NUMBER OF CLUSTERS
        clusters = scipy.cluster.hierarchy.fcluster(Z, 4,
                                                    criterion='maxclust')
        nclusters = clusters.size
        num = max(clusters)
        c = []
        for i in range(1, num):
            c.append([names[x] for x in range(nclusters) if clusters[x] == i])
        json.dump(c, open('clusters.txt', 'w'), indent=4)


def add_node(node, parent):
    """ A Helper method for outputting the dendrogram
    linkage for visualisation in d3.js"""
    newNode = dict(node_id=node.id, children=[])
    parent["children"].append(newNode)
    # Recursively add the current node's children
    if node.left:
        add_node(node.left, newNode)
    if node.right:
        add_node(node.right, newNode)


def label_tree(n, names):
    """ Helper function to label the tree """
    id2name = dict(zip(range(len(names)), names))
    # If it's a leaf node we have the name
    if len(n["children"]) == 0:
        leafNames = [id2name[n["node_id"]]]
    # Otherwise flatten all the leaves in the subtree
    else:
        leafNames = reduce(lambda ls, c: ls + label_tree(c, names),
                           n["children"], [])
    # Delete the node id as it is no longer needed
    del n["node_id"]

    n["name"] = "-".join(sorted(map(str, leafNames)))
    if len(n["name"]) > 16:
        n["name"] = n["name"][:16] + '...'
    # Labeling convention: "-" separates leaf names

    return leafNames


def area_tri(a, b, c):
    """ Calculate the area of a triangle given by its 3 vertices
    using the cross product formula |AxB|/2"""
    return np.linalg.norm(np.cross(a - b, c - b)) / 2


def get_contrib_percentage(vertices, indices, internal,
                           external, distances,
                           dp=8, restrict=True,
                           order=False):
    """ Given a the triangles that make up a hirshfeld surface,
    and lists of the closest internal and external atoms along
    with their respective distances from the surface,
    calculate the makeup of the hirshfeld surface in terms of
    which element->element interactions are responsible for that
    area """
    contrib = defaultdict(float)
    contrib_p = defaultdict(float)
    # setting defaults for these
    avg_d = 0.
    threshold = 1.

    if restrict:  # Check if we can restrict
        unique = np.unique(np.append(internal, external))
        for sym in unique:
            if sym not in data.vdw_radii:
                log("{} not found in Van Der Waal's Radii list".format(sym))
                restrict = False

    for i, (chsymi, chsyme) in enumerate(zip(internal, external)):

        # are we restricting to interactions closer than vdw radii?
        if restrict:
            avg_d = np.mean(distances[indices[i]])
            threshold = data.vdw_radii[chsymi] + data.vdw_radii[chsyme]
            if avg_d > threshold:
                continue

        # Check if the order of the interaction is important
        if(not order):
            chsymi, chsyme = sorted((chsymi, chsyme))

        # Key in the form "internal -> external" e.g. "F -> H"
        key = "{0} -> {1}".format(chsymi, chsyme)

        # get triangle indices, and find area of triangle
        tri = [vertices[n] for n in indices[i]]
        area = area_tri(tri[0], tri[1], tri[2])

        contrib[key] += area

    for x in contrib:
        p = np.round(contrib[x] / sum(contrib.values()), decimals=8)
        contrib_p[x] = p

    return contrib, contrib_p
