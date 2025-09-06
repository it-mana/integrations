# :coding: utf-8
# :copyright: Copyright (c) 2025 Mana


import logging
import os
import sys

import ftrack_api

LOCATION_DIRECTORY = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "location")
)

sys.path.append(LOCATION_DIRECTORY)

logger = logging.getLogger("com.ftrack.recipes.customise_structure.hook")


def append_path(path, key, environment):
    """Append *path* to *key* in *environment*."""
    try:
        environment[key] = os.pathsep.join([environment[key], path])
    except KeyError:
        environment[key] = path

    return environment


def modify_application_launch(event):
    """Modify the application environment to include our location plugin."""
    try:
        # Check if this is an application launch (has options.env structure)
        if "options" in event["data"] and isinstance(
            event["data"]["options"], dict
        ):
            # Application launched from ftrack connect
            logger.debug("Application launch event detected")

            # Get or create env dictionary
            if "env" not in event["data"]["options"]:
                event["data"]["options"]["env"] = {}

            environment = event["data"]["options"]["env"]
        else:
            # API or publisher scenario - create options.env structure
            logger.debug("API/publisher event detected")

            if "data" not in event:
                event["data"] = {}

            if "options" not in event["data"]:
                event["data"]["options"] = {}

            if "env" not in event["data"]["options"]:
                event["data"]["options"]["env"] = {}

            environment = event["data"]["options"]["env"]

        # Now we have a valid environment dictionary, add our paths
        append_path(LOCATION_DIRECTORY, "FTRACK_EVENT_PLUGIN_PATH", environment)
        append_path(LOCATION_DIRECTORY, "PYTHONPATH", environment)

        logger.info(
            "Connect plugin modified launch hook to register location plugin."
        )
    except Exception as e:
        logger.error(f"Error modifying application launch: {e}")
        logger.debug(f"Event structure: {event}")


def register(api_object, **kw):
    """Register plugin to api_object."""

    # Validate that api_object is an instance of ftrack_api.Session. If not,
    # assume that register is being called from an incompatible API
    # and return without doing anything.
    if not isinstance(api_object, ftrack_api.Session):
        # Exit to avoid registering this plugin again.
        return

    logger.info("Connect plugin discovered.")

    import mana_location_plugin

    mana_location_plugin.register(api_object)

    # Location will be available from within the dcc applications.
    api_object.event_hub.subscribe(
        "topic=ftrack.connect.application.launch", modify_application_launch
    )

    # Location will be available from actions
    api_object.event_hub.subscribe(
        "topic=ftrack.action.launch", modify_application_launch
    )
