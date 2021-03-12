# Rebuild the UID index by clearing and reindexing.
# And try to fix duplicate UIDs.
# This can at least happen when you import a zexp twice, in different folders.
#
# For updates and more such scripts, see https://github.com/zestsoftware/plonescripts
#
# Run this with:
# bin/instance run scripts/fix_uid_index.py
#
# Note: this script only works on Python 3!
# But this is only because of f-strings, so should be easily fixable.
# Tested on Plone 5.2.

import sys
import transaction
from plone.uuid.handlers import addAttributeUUID
from plone.uuid.interfaces import ATTRIBUTE_NAME
from zope.component import getUtility
from zope.component.hooks import setSite
from zope.intid.interfaces import IIntIds
from Testing.makerequest import makerequest


# NOTE: change this to your site id:
site = app.Plone
catalog = site.portal_catalog
setSite(site)
makerequest(site)

# Problems in the UID index could also mean some objects have no intid.
intids = getUtility(IIntIds)
fixed_intid = 0

index = catalog.Indexes['UID']
# _index: UID -> doc id
# _unindex: doc id -> UID
_index_keys = index._index.keys()
_index_values = index._index.values()
_unindex_keys = index._unindex.keys()
_unindex_values = index._unindex.values()
print(f"Number of _index uid keys:      {len(_index_keys)}, unique: {len(set(_index_keys))}")
print(f"Number of _index doc id values: {len(_index_values)}, unique: {len(set(_index_values))}")
print(f"Number of _unindex doc id keys: {len(_unindex_keys)}, unique: {len(set(_unindex_keys))}")
print(f"Number of _unindex uid values:  {len(_unindex_values)}, unique: {len(set(_unindex_values))}")
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
        print(f"UID {uid} is missing from _index keys. docid {docid}, path {path}")
        missing += 1
    if docid not in _index_values:
        # Note: this seems the main problem.
        path = catalog.getpath(docid)
        print(f"Doc id {docid} is missing from _index values. UID {uid}, path {path}")
        missing += 1
        recreate.append(path)
    if uid in seen_uids:
        # This probably only happens if docid is not in _index_values
        # (see previous condition), but let's check and report separately.
        print(f"UID {uid} is duplicate in the _unindex values:")
        for (key, value) in index._unindex.items():
            if value != uid:
                continue
            path = catalog.getpath(key)
            print(f"- doc id {key} path {path}")
            obj = app.unrestrictedTraverse(path)
            try:
                intids.getId(obj)
            except KeyError:
                intids.register(obj)
                fixed_intid += 1
                print(f"- Registered intid for object at path {path}")
    else:
        seen_uids.add(uid)

if not (missing or recreate):
    print("No UIDs are missing or need to be recreated.")
    sys.exit(0)

if recreate:
    print(f"We will recreate {len(recreate)} UIDs/UUIDs that are currently duplicate.")
    print("You might need to manually fix some links.")
    print("We have no way of knowing if a link should use resolveuid/old_uid or resolveuid/new_uid.")
    print("Perhaps we could query the relation catalog to see which relations an item has.")

for path in recreate:
    obj = app.unrestrictedTraverse(path)
    old_uuid = obj.UID()
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
    print(f"Changed UID from {old_uuid} to {new_uuid} for {path}")

# Even after the above fix, the clear and reindes is still needed.
print('Clearing UID index')
index.clear()
print('Reindexing UID index')
catalog._catalog.reindexIndex('UID', site.REQUEST)

if len(index._index) != len(index._unindex):
    print(f"ERROR: The UID _index has {len(index._index)} entries and its reverse _unindex has {len(index._unindex)}")
    sys.exit(1)
print('Committing...')
tr = transaction.get()
tr.note("Fixed inconsistencies in UID index.")
transaction.commit()
