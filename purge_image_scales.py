# Run this with:
# bin/instance run scripts/purge_image_scales.py
#
# Add --dry-run to change nothing and only get a report.
#
# For updates and more such scripts, see https://github.com/zestsoftware/plonescripts
import sys
import transaction
from Products.CMFCore.utils import getToolByName
from plone.scale.storage import AnnotationStorage
from zope.component.hooks import setSite

# Keep scales of at most X days older than their context:
DAYS = -1
# Commit after these many changes:
LIMIT = 1000

if "--dry-run" in sys.argv:
    dry_run = True
    print("Dry run selected, will not commit changes.")
else:
    dry_run = False

# Get all Plone Sites.  'app' is the Zope root.
plones = [
    obj for obj in app.objectValues() if getattr(obj, "portal_type", "") == "Plone Site"
]


def commit(note):
    print(note)
    if dry_run:
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
    catalog = getToolByName(site, "portal_catalog")
    count = 0
    purged = 0
    if hasattr(catalog, "getAllBrains"):
        brains = catalog.getAllBrains()
    else:
        brains = catalog.unrestrictedSearchResults()
    for brain in brains:
        try:
            obj = brain.getObject()
        except:
            continue
        savepoint = transaction.savepoint()
        ann = AnnotationStorage(obj)
        try:
            ann.storage
        except TypeError:
            # This happens when the context cannot be annotated, for
            # example for a plone.app.discussion comment.
            continue
        # We want to remove all scales that are X days older than the
        # last modification date of the object.
        final_date = obj.modified() - DAYS
        changed = False
        to_delete = []
        for key, value in ann.items():
            if value["modified"] < final_date.millis():
                to_delete.append(key)
                changed = True
        for key in to_delete:
            # This may easily give an error, as it tries to remove
            # two keys: del ann[key]
            del ann.storage[key]
        purged += len(to_delete)
        if not changed:
            # This avoids adding an empty annotation for items that
            # will never store scales.
            savepoint.rollback()
        else:
            count += 1
            if count % LIMIT == 0:
                note = (
                    "Purged %d outdated image scales for %d items in "
                    "Plone Site %s." % (purged, count, site.id)
                )
                commit(note)

    note = (
        "Finished purging %d outdated image scales for %d items in "
        "Plone Site %s." % (purged, count, site.id)
    )
    commit(note)

print("Done.")
