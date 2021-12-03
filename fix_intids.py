# Run this with:
# bin/instance run scripts/fix_intids.py
# or with extra options: --dry-run --site=plone_portal --no-populate
# For background on the stranger parts of this script, see
# https://github.com/plone/five.intid/issues/9#issuecomment-802940554

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
    "--no-repopulate",
    action="store_false",
    default=True,
    dest="repopulate",
    help=(
        "Do not repopulate the BTrees. "
        "By default we do repopulate them, because the hash function may have changed. "
        "Regardless of command line options, we always repopulate when we see it is needed."
    ),
)
parser.add_argument(
    "--site",
    default="",
    dest="site",
    help="Single site id to work on. Default is to work on all.",
)
# sys.argv will be something like:
# ['.../parts/instance/bin/interpreter', '-c',
#  'scripts/fix_intids.py', '--dry-run', '--site=plone_portal']
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


def actual_path(persistentkey):
    obj = api.content.get(UID=persistentkey.object.UID())
    try:
        return "/".join(obj.getPhysicalPath())
    except Exception:
        pass


def remove_refs_missing_from_ids(intids):
    # The intids catalog has two BTrees:
    # - ids: mapping from key reference to intid
    # - refs: mapping from intid to key reference
    refs_missing_from_ids = [
        (uid, key) for (uid, key) in intids.refs.items() if key not in intids.ids
    ]
    print(
        "Found %d intid references that are missing from the ids." % len(refs_missing_from_ids)
    )
    for uid, key in refs_missing_from_ids:
        print(
            "Deleting reference mapping intid %s to key with object %s and path %s." %
            (uid, key.object, key.path)
        )
        del intids.refs[uid]
    return len(refs_missing_from_ids)


def remove_ids_missing_from_refs(intids):
    ids_missing_from_refs = [
        (key, uid) for (key, uid) in intids.ids.items() if uid not in intids.refs
    ]
    print(
        "Found %d intid ids that are missing from the refs." % len(ids_missing_from_refs)
    )
    for key, uid in ids_missing_from_refs:
        print(
            "Deleting id mapping key with object %s and path %s to intid %s." %
            (key.object, key.path, uid)
        )
        del intids.ids[key]
    return len(ids_missing_from_refs)


for site in plones:
    print("")
    print("Handling Plone Site %s." % site.id)
    setSite(site)
    catalog = api.portal.get_tool(name="portal_catalog")
    intids = getUtility(IIntIds)

    # First things first.  There might have been subtle changes to the
    # __hash__ method of key references, and this is not good when they are
    # used as keys in a dictionary (or BTree in our case).
    # See https://docs.python.org/3.8/glossary.html#term-hashable
    # and https://docs.python.org/3.8/reference/datamodel.html#object.__hash__
    # So we may need to repopulate the BTrees.
    repopulated = False
    id_keys_missing_from_id = [key for key in intids.ids if key not in intids.ids]
    if id_keys_missing_from_id:
        print(
            "%s keys from intids.ids are missing from intid.ids. "
            "This sounds weird, but may happen when the hash method changes." %
            len(id_keys_missing_from_id)
        )
    # All keys should be unique, otherwise we run into errors,
    # which might need a fix in the __hash__ method in five.intid.
    keys = list(intids.ids.keys())
    all_unique = len(keys) == len(set(keys))
    if not all_unique:
        print("Only %d out of %d keys are unique." % (len(set(keys)), len(keys)))
    if options.repopulate or id_keys_missing_from_id or not all_unique:
        print("Repopulating BTrees.")
        repopulated = True
        # The refs and ids should be a mirror of each other.
        # There might be inconsistencies between refs and ids,
        # so let's take the refs as the original and rebuild from there.
        # Note: we take the refs as base, because their keys are simple integers,
        # which means it is less likely that something is broken in the refs.
        intid_refs = list(intids.refs.items())
        intids.ids.clear()
        intids.refs.clear()
        for key, value in intid_refs:
            intids.refs[key] = value
            intids.ids[value] = key
        print("Done repopulating BTrees.")
        # We check again.
        id_keys_missing_from_id = [key for key in intids.ids if key not in intids.ids]
        if id_keys_missing_from_id:
            print(
                "ERROR: %d keys from intids.ids are missing from intid.ids. "
                "This is after rebuilding the BTrees, so something is wrong." %
                len(id_keys_missing_from_id)
            )
            sys.exit(1)
        keys = list(intids.ids.keys())
        all_unique = len(keys) == len(set(keys))
        if not all_unique:
            print(
                "ERROR: Only %d out of %d keys are unique. "
                "This is after rebuilding the BTrees, so something is wrong." %
                (len(set(keys)), len(keys))
            )
            sys.exit(1)

    # Look for keys with a broken path.  Fix them.
    keys_with_a_broken_path = [
        key
        for key in intids.ids
        if key.path and not app.unrestrictedTraverse(key.path, None)
    ]
    print("%d keys with broken path" % len(keys_with_a_broken_path))
    # Some can be fixed, some need to be removed.
    fixed_broken = 0
    removed_broken = 0
    for key in keys_with_a_broken_path:
        # Remove the item.
        uid = intids.ids[key]
        del intids.refs[uid]
        del intids.ids[key]
        # Maybe we can find a good path.
        proper_path = actual_path(key)
        if proper_path:
            # This fixes lots of keys to objects that have been moved.
            # Setting key.path is not enough: the change is not persisted.
            # And it is actually bad: keys in dictionaries or BTrees
            # must not change.
            # So we must first remove the item (which we already did),
            # then change it, then add it again.
            key.path = proper_path
            intids.refs[uid] = key
            intids.ids[key] = uid
            fixed_broken += 1
        else:
            # key.object.UID() is not known in the portal_catalog.
            removed_broken += 1

    print(
        "Removed, fixed and re-added %d keys with broken paths, and removed %d completely." %
        (fixed_broken, removed_broken)
    )

    # Look for keys with a path outside of the site.  Remove these.
    keys_with_path_outside_of_site = [
        key for key in intids.ids if key.path and not key.path.startswith("/%s" % site.id)
    ]
    print("%d keys with path outside of site" % len(keys_with_path_outside_of_site))

    removed_outside = 0
    for key in keys_with_path_outside_of_site:
        uid = intids.ids[key]
        del intids.refs[uid]
        del intids.ids[key]
        removed_outside += 1
    if removed_outside:
        print("Deleted all keys with path outside of site.")

    # When the refs and ids have been repopulated, they are probably fine,
    # otherwise they may not entirely be in sync:
    # - The same object has one intid in the ids and another in the refs.
    # - The same intid has a different object in ids and refs.
    # Check this, and remove inconsistent items, getting back a count.
    refs_missing_from_ids = remove_refs_missing_from_ids(intids)
    ids_missing_from_refs = remove_ids_missing_from_refs(intids)
    # It seems needed to run both twice.
    refs_missing_from_ids += remove_refs_missing_from_ids(intids)
    ids_missing_from_refs += remove_ids_missing_from_refs(intids)

    # The above fixes should be enough to fix all inconsistencies.
    # But there might still be objects without an intid.
    # Registering them was the initial purpose of this script.
    # So go through all content.
    fixed_intid = 0
    brains = list(catalog.getAllBrains())
    print("Found %d  brains." % len(brains))
    for brain in brains:
        try:
            obj = brain.getObject()
        except (KeyError, ValueError, AttributeError):
            continue
        try:
            obj_intid = intids.getId(obj)
        except KeyError:
            print("Registering intid for %s" % brain.getPath())
            obj_intid = intids.register(obj)
            fixed_intid += 1
        # We have an intid.  Get the key for this intid
        # and check that it has the same path.
        ref = intids.refs[obj_intid]
        if ref.path != brain.getPath():
            print(
                "WARNING: Object at path %s has intid %s which points to other path %s." %
                (brain.getPath(), obj_intid, ref.path)
            )
            intids.unregister(obj)
            obj_intid = intids.register(obj)
            print("Reregistered intid for %s" % brain.getPath())
            fixed_intid += 1
            ref = intids.refs[obj_intid]
            if ref.path != brain.getPath():
                # Yes, I have seen this happen...
                print(
                    "ERROR: Object at path %s has intid %s which STILL points to other path %s" %
                    (brain.getPath, obj_intid, ref.path)
                )

    if not (
        repopulated
        or fixed_broken
        or removed_broken
        or removed_outside
        or refs_missing_from_ids
        or ids_missing_from_refs
        or fixed_intid
    ):
        print("No fixes were done.")
        # Abort the transaction so we can start a new one.
        transaction.abort()
        continue
    note = (
        "Fixed intids for %s: "
        "repopulated BTrees: %d, "
        "fixed %d keys with broken paths, "
        "removed %d keys with broken paths, "
        "removed %d keys with path outside of site, "
        "removed %d refs missing from ids, "
        "removed %d ids missing from refs, "
        "registered %d new intids."
        % (
            site.id,
            repopulated,
            fixed_broken,
            removed_broken,
            removed_outside,
            refs_missing_from_ids,
            ids_missing_from_refs,
            fixed_intid,
        )
    )
    commit(note)
    print("Done.")
