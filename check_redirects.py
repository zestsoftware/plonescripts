# Check the automatic and manual redirects in all Plone Sites.
# Run this with:
# bin/instance run check_redirects.py
# or with extra options: --verbose --fix --site=Plone
#
# For updates and more such scripts, see https://github.com/zestsoftware/plonescripts
from plone.app.redirector.interfaces import IRedirectionStorage
from zope.component import getUtility
from zope.component.hooks import setSite

import argparse
import sys
import transaction

parser = argparse.ArgumentParser()
parser.add_argument(
    "--fix",
    action="store_true",
    default=False,
    dest="fix",
    help="Fix. Remove useless or not working redirects.",
)
parser.add_argument(
    "--verbose",
    action="store_true",
    default=False,
    dest="verbose",
    help="Verbose. Prints all non-existing paths.",
)
parser.add_argument(
    "--site",
    default="",
    dest="site",
    help="Single site id to work on. Default is to work on all.",
)
# sys.argv will be something like:
# ['.../parts/instance/bin/interpreter', '-c',
#  'scripts/check-redirects.py', '--dry-run', '--site=Plone']
# Ignore the first three.
options = parser.parse_args(args=sys.argv[3:])

if options.fix:
    print("Fix selected, will remove useless or not working redirects.")

# 'app' is the Zope root.
# Get Plone Sites to work on.
if options.site:
    # Get single Plone Site.
    plones = [getattr(app, options.site)]
else:
    # Get all Plone Sites.
    plones = [
        obj
        for obj in app.objectValues()  # noqa
        if getattr(obj, "portal_type", "") == "Plone Site"
    ]


def commit(note):
    print(note)
    # Commit transaction and add note.
    tr = transaction.get()
    tr.note(note)
    transaction.commit()


for site in plones:
    print("")
    print("Handling Plone Site %s." % site.id)
    setSite(site)
    storage = getUtility(IRedirectionStorage)
    print("There are {0} sources (redirects)".format(len(storage._paths.keys())))
    print(
        "There are {0} targets (reverse redirects)".format(len(storage._rpaths.keys()))
    )
    print(
        "Looking for targets that do *not* exist, so that a redirect would give a 404 NotFound..."
    )
    bad_rpaths = []
    for key in storage._rpaths.keys():
        if app.unrestrictedTraverse(key, None) is not None:
            continue
        bad_rpaths.append(key)
        if options.verbose:
            sources = storage.redirects(key)
            print("Non-existing target: {0} <- {1}".format(key, sources))
    print("Found {0} targets that do not exist.".format(len(bad_rpaths)))
    print(
        "Looking for sources of redirects that *do* exist, so that the redirect is inactive..."
    )
    bad_paths = []
    for key in storage._paths.keys():
        if app.unrestrictedTraverse(key, None) is None:
            continue
        bad_paths.append(key)
        if options.verbose:
            target = storage.get(key)
            print("Existing source: {0} -> {1}".format(key, target))
    print("Found {0} sources that do exist.".format(len(bad_paths)))
    if not (bad_rpaths or bad_paths):
        print("No fixes are needed.")
        # Abort the transaction so we can start a new one.
        transaction.abort()
        continue
    if not options.fix:
        print("Option --fix not selected, so not fixing anything.")
        continue
    print("Fixing...")
    for key in bad_rpaths:
        storage.destroy(key)
    for key in bad_paths[:12]:
        if not storage.has_path(key):
            # already cleaned up by 'destroy' above
            continue
        storage.remove(key)
    note = "Removed {0} non-existing redirect targets and {1} existing redirect sources for site {2}.".format(
        len(bad_rpaths), len(bad_paths), site.id
    )
    commit(note)
    print("Done.")
