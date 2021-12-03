# Rebuild the UID index by clearing and reindexing.
# Also registers a new UID for items that have the same UID as another item.
# This can at least happen when you import a zexp twice, in different folders.
#
# One of them will keep its original UID, and you cannot influence which one this is.
# This might matter when there are resolveuid links in the site.
#
# For updates and more such scripts, see https://github.com/zestsoftware/plonescripts
#
# Run this with:
# bin/instance run scripts/fix_uid_index.py
#
# Note: this script only works on Python 3!
# But this is only because of f-strings, so should be easily fixable.
# Tested on Plone 5.2.

import argparse
import sys
import transaction
from plone import api
from plone.app.redirector.interfaces import IRedirectionStorage
from plone.uuid.handlers import addAttributeUUID
from plone.uuid.interfaces import ATTRIBUTE_NAME
from zope.component import getUtility
from zope.component.hooks import setSite
from zope.intid.interfaces import IIntIds


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
#  'scripts/fix_uid_index.py', '--dry-run', '--site=nl']
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
    actual_catalog = catalog._catalog
    uncatalog_paths = []
    for path in actual_catalog.uids.keys():
        try:
            obj = app.unrestrictedTraverse(path)
        except KeyError:
            print(
                "The catalog has an object at path %s but nothing exists there." % path
            )
            uncatalog_paths.append(path)
            continue
        # This might find an item by acquisition.
        # migration-law/migration-law/migration-law/research.htm
        # may actually be migration-law/research.htm
        actual_path = "/".join(obj.getPhysicalPath())
        if path == actual_path:
            continue
        print(
            "Object is indexed at %s but is actually at a different path, likely due to acquisition: %s" %
            (path, actual_path)
        )
        uncatalog_paths.append(path)
    for path in uncatalog_paths:
        print("Uncataloging object at %s" % path)
        actual_catalog.uncatalogObject(path)

    # Problems in the UID index could also mean some objects have no intid.
    intids = getUtility(IIntIds)
    fixed_intid = 0

    index = catalog.Indexes["UID"]
    # _index: UID -> doc id
    # _unindex: doc id -> UID
    _index_keys = index._index.keys()
    _index_values = index._index.values()
    _unindex_keys = index._unindex.keys()
    _unindex_values = index._unindex.values()
    print(
        "Number of _index uid keys:      %d, unique: %d" %
        (len(_index_keys), len(set(_index_keys)))
    )
    print(
        "Number of _index doc id values: %d, unique: %d" %
        (len(_index_values), len(set(_index_values)))
    )
    print(
        "Number of _unindex doc id keys: %d, unique: %d" %
        (len(_unindex_keys), len(set(_unindex_keys)))
    )
    print(
        "Number of _unindex uid values:  %d, unique: %d" %
        (len(_unindex_values), len(set(_unindex_values)))
    )
    missing = 0
    seen_uids = set()
    # Gather a list of paths for which we will create a new uuid.
    recreate = []
    # The _index and _unindex could be inconsistent in various ways.
    # Not all inconsistencies may be possible.
    # It depends on what the exact problem is in our site.
    # So we may do too many or too few checks here.  Let's see.
    for docid, uid in index._unindex.items():
        if uid not in _index_keys:
            # Note: I have not seen this.
            path = catalog.getpath(docid)
            print(
                "UID %s is missing from _index keys. docid %s, path %s" %
                (uid, docid, path))
            missing += 1
        if docid not in _index_values:
            # Note: this seems the main problem.
            path = catalog.getpath(docid)
            print(
                "Doc id %s is missing from _index values. UID %s, path %s" %
                (docid, uid, path)
            )
            missing += 1
            recreate.append(path)
        if uid in seen_uids:
            # This probably only happens if docid is not in _index_values
            # (see previous condition), but let's check and report separately.
            print("UID %s is duplicate in the _unindex values:" % uid)
            for (key, value) in index._unindex.items():
                if value != uid:
                    continue
                path = catalog.getpath(key)
                print("- doc id %s path %s" % (key, path))
                try:
                    obj = app.unrestrictedTraverse(path)
                except KeyError:
                    print("Ignoring unreachable path when checking duplicate UID: %s" % path)
                    continue
                try:
                    intids.getId(obj)
                except KeyError:
                    intids.register(obj)
                    fixed_intid += 1
                    print("- Registered intid for object at path %s" % path)
        else:
            seen_uids.add(uid)

    if not (missing or recreate or fixed_intid or uncatalog_paths):
        print(
            "No UIDs are missing or need to be recreated, and no intids were added, "
            "and no paths were uncataloged."
        )
        continue

    if recreate:
        print(
            "We will recreate %d UIDs/UUIDs that are currently duplicate." % len(recreate)
        )
        print("You might need to manually fix some links.")
        print(
            "We have no way of knowing if a link should use resolveuid/old_uid or resolveuid/new_uid."
        )
        print(
            "Perhaps we could query the relation catalog to see which relations an item has."
        )

    for path in recreate:
        try:
            obj = app.unrestrictedTraverse(path)
        except KeyError:
            print("Ignoring unreachable path to recreate UID: %s" % path)
            continue
        old_uuid = obj.UID()
        # This might find an item by acquisition.
        # migration-law/migration-law/migration-law/research.htm
        # may actually be migration-law/research.htm
        actual_path = "/".join(obj.getPhysicalPath())
        if actual_path != path:
            print(
                "Wanted to recreate UID for path %s, but this leads to other path %s. Ignoring." %
                (path, actual_path)
            )
            continue
        # Note: currently this gives zero results,
        # because the index is inconsistent for this uid:
        #   catalog.unrestrictedSearchResults(UID=old_uuid)
        # After this fix plus index clear+reindex, it works again.
        delattr(obj, ATTRIBUTE_NAME)
        # Call the event handler that adds a UUID:
        addAttributeUUID(obj, None)
        # Reindex the UID index for this object and update its metadata in the catalog.
        obj.reindexObject(idxs=["UID"])
        new_uuid = obj.UID()
        print(
            "Changed UID from %s to %s for %s" %
            (old_uuid, new_uuid, path)
        )

    # Even after the above fix, the clear and reindex is still needed.
    print("Clearing UID index")
    index.clear()
    print("Reindexing UID index")
    catalog._catalog.reindexIndex("UID", site.REQUEST)

    if len(index._index) != len(index._unindex):
        print(
            "ERROR for site %s: after all fixes and reindexing, "
            "the UID _index has %d entries "
            "and its reverse _unindex has %d" %
            (site.id, len(index._index), len(index._unindex))
        )
        print("ERROR: NOT COMMITTING ANYTHING.")
        # sys.exit(1)
        continue

    # On a hunch, let's rebuild the redirection storage.  Only takes a few seconds.
    storage = getUtility(IRedirectionStorage)
    storage._rebuild()

    print("Committing...")
    tr = transaction.get()
    tr.note("Fixed inconsistencies in UID index for site %s." % site.id)
    transaction.commit()
