# :coding: utf-8
# :copyright: Copyright (c) 2024 Mana

import json
import os
import platform
import sys

import ftrack_api

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "dependencies"))

from structure import ManaStructure

# Define the location name
location_name = "mana.studio"


def get_prefix(location_name):

    # Define the path to the mount_points.json file
    base_dir = os.path.dirname(os.path.abspath(__file__))
    mount_points_file = os.path.abspath(
        os.path.join(base_dir, "..", "config.json")
    )

    # Load mount points from JSON file
    with open(mount_points_file, "r") as file:
        mount_points = json.load(file)

    # Determine the current OS type
    os_type = platform.system().lower()
    return mount_points[location_name][os_type]


def configure_locations(event):
    session = event["data"]["session"]

    location = session.ensure("Location", {"name": location_name})
    location.priority = 0
    # ftrack_api.mixin(
    #     location, ftrack_api.entity.location.UnmanagedLocationMixin
    # )
    location.structure = ManaStructure()

    location.accessor = ftrack_api.accessor.disk.DiskAccessor(
        prefix=get_prefix(location_name)
    )


def register(session, **kw):
    # Validate that session is an instance of ftrack_api.Session. If not,
    # assume that register is being called from an incompatible API
    # and return without doing anything.
    if not isinstance(session, ftrack_api.Session):
        # Exit to avoid registering this plugin again.
        return

    session.event_hub.subscribe(
        "topic=ftrack.api.session.configure-location", configure_locations
    )
