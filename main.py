#!/usr/bin/python
"""Usage:
    sclcc hist (--batch <dir> | <file>) [options]
    sclcc surface (--batch <dir> | <file>) [options]
    sclcc (--version | --help | -h)

Simple Command-Line Computational Chemistry (SCLCC)

This program deals primarily with the histograms or 'fingerprints' generated
from the hirshfeld surfaces of various molecular crystals generated by tonto.

In addition this program can:

* Perform clustering on the generated fingerprints (using hist with --batch)
* Generate and output the percentage contribution to hirshfeld surface from
various elements. (using surface command)

Options:
    -h, --help                     Show this help message and exit.
    --version                      Show program's version number and exit.
    -b=NUM, --bins=NUM             Set the number of bins to use
                                   in the histogram. [default: 100]
    -t=TEST, --test=TEST           Select which test will be used.
                                   [default: sp]
    -p, --save-figures             Plot histograms calculated and
                                   save them to file.
    -n=N, --threads=N              The number of processes to parse
                                   files with. [default: 4]
    -i=ATOM, --internal-atom=ATOM  Restrict the closest internal atom
                                   in the histogram
    -e=ATOM, --external-atom=ATOM  Restrict the closest external atom
                                   in the histogram
    -j=FILE, --json=FILE           Dump the dendrogram tree to JSON
"""

# Core imports
import sys
import time
import os
# local imports
import hist
import calc
import fileio as fio
import visual
from docopt import docopt

version = "0.23"
test_f = {'sp': calc.spearman_roc,
          'kt': calc.kendall_tau,
          'hd': calc.hdistance}
test_names = {'sp': 'Spearman rank order coefficient',
              'kt': 'Kendall Tau',
              'hd': 'Custom histogram distance'}
args = docopt(__doc__, version=version)

# *******        MAIN PROGRAM           ****** #


def main():
    """
    This program currently rounds distance matrices to 5 d.p.
    due to floating point arithmetic problems!!'
    """
    mtest = test_f[args['--test']]
    tname = test_names[args['--test']]
    start_time = time.time()

    if args['hist']:
        i_atom = args['--internal-atom']
        e_atom = args['--external-atom']
        threads = int(args['--threads'])
        bins = int(args['--bins'])
        png = args['--save-figures']

        if args['<file>']:
            fname = args['<file>']
            h, name = fio.process_file(fname, resolution=bins,
                                       write_png=png, i=i_atom, e=e_atom)

        elif args['<dir>']:
            dirname = args['<dir>']
            # Program is being run to batch process a directory of cxs files
            restrict_str = '{0} -> {1}'
            histograms, names = fio.batch_process(dirname, resolution=bins,
                                                  write_png=png,
                                                  threads=threads,
                                                  i=i_atom, e=e_atom)

            print 'Generating matrix using {0}'.format(tname)
            mat = calc.get_correl_mat(histograms, test=mtest)
            calc.cluster(mat, names, tname, dump=args['--json'])

    if args['surface']:
        if args['<file>']:
            fname = args['<file>']
            if not fname.endswith('.cxs'):
                print 'WARNING: {0} does not have .cxs extension'.format(fname)
            # Generate the percentage contribution of each element
            x, y, a = fio.readcxsfile_c(fname)
            formula, vertices, indices, internal, external = a
            contrib, contrib_p = calc.get_contrib_percentage(vertices,
                                                             indices,
                                                             internal,
                                                             external,
                                                             dp=1)
            print 'Molecular Formula: {0}'.format(formula)

            for key in sorted(contrib_p, key=lambda key: contrib_p[key]):
                print '{0} contribution: {1} %'.format(key, contrib_p[key])

    # If we got here, program was success!
    print 'Process complete: {0:.2} s'.format(time.time() - start_time)
    sys.exit(0)


# Python's way of dealing with main
if __name__ == '__main__':
    main()
