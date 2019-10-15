# Run this with:
# bin/instance run scripts/register_intids.py
# or with extra options: --dry-run --site=plone
from plone import api
from zope.component import getUtility
from zope.component.hooks import setSite
from zope.intid.interfaces import IIntIds

import argparse
import sys
import transaction

parser = argparse.ArgumentParser()
parser.add_argument(
    "--dry-run",
    action="store_true",
    default=False,
    dest="dry_run",
    help="Dry run. No changes will be saved.",
)
parser.add_argument(
    "--site",
    default="",
    dest="site",
    help="Single site id to work on. Default is to work on all.",
)
# sys.argv will be something like:
# ['.../parts/instance/bin/interpreter', '-c',
#  'scripts/register_intids.py', '--dry-run', '--site=nl']
# Ignore the first three.
options = parser.parse_args(args=sys.argv[3:])

if options.dry_run:
    print("Dry run selected, will not commit changes.")

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
    if options.dry_run:
        print("Dry run selected, not committing.")
        return
    # Commit transaction and add note.
    tr = transaction.get()
    tr.note(note)
    transaction.commit()


for site in plones:
    print("")
    print("Handling Plone Site %s." % site.id)
    setSite(site)
    catalog = api.portal.get_tool(name="portal_catalog")
    intids = getUtility(IIntIds)
    fixed_intid = 0
    for brain in catalog.unrestrictedSearchResults():
        try:
            obj = brain.getObject()
        except (KeyError, ValueError, AttributeError):
            continue
        try:
            intids.getId(obj)
        except KeyError:
            intids.register(obj)
            fixed_intid += 1
    if not fixed_intid:
        print("No fixes were needed.")
        # Abort the transaction so we can start a new one.
        transaction.abort()
        continue
    note = "Registered {0} intids for {1}".format(
        fixed_intid, site.id
    )
    commit(note)
    print("Done.")
