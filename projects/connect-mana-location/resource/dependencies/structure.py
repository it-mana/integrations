# :coding: utf-8
# :copyright: Copyright (c) 2025 Mana

import json
import os
import re
import unicodedata
import uuid
from builtins import str

import ftrack_api.structure.base
import ftrack_api.symbol


def get_resolution_id(resolution):

    # Define the path to the resolutions.json file
    base_dir = os.path.dirname(os.path.abspath(__file__))
    resolutions_file = os.path.abspath(
        os.path.join(base_dir, "..", "config.json")
    )

    # Load mount points from JSON file
    with open(resolutions_file, "r") as file:
        resolutions = json.load(file)

    if resolution not in resolutions["resolution_id"]:
        return uuid.uuid4().int % 957 + len(
            resolutions.get("resolution_id", {})
        )

    return resolutions["resolution_id"][resolution]


class ManaStructure(ftrack_api.structure.base.Structure):

    def __init__(self, illegal_character_substitute="_"):
        """Initialise structure."""
        super(ManaStructure, self).__init__()
        self.illegal_character_substitute = illegal_character_substitute

    def _get_parts(self, entity):
        session = entity.session

        version = entity["version"]

        if version is ftrack_api.symbol.NOT_SET and entity["version_id"]:
            version = session.get("AssetVersion", entity["version_id"])

        error_message = (
            "Component {0!r} must be attached to a committed "
            "version and a committed asset with a parent context.".format(
                entity
            )
        )

        if version is ftrack_api.symbol.NOT_SET or version in session.created:
            raise ftrack_api.exception.StructureError(error_message)

        link = version["link"]

        if not link:
            raise ftrack_api.exception.StructureError(error_message)

        structure_names = [item["name"] for item in link[1:-1]]

        project_id = link[0]["id"]
        project = session.get("Project", project_id)
        # Get project attributes
        version_type = version["task"]["type"]["name"]

        asset = version["asset"]

        version_number = self._format_version(version["version"])
        task_name = version["task"]["name"]
        task_parent = version["task"]["parent"]["name"]

        ### Build system path
        parts = []
        parts.append(project["name"])

        if structure_names:
            parts.extend(structure_names)

        parts.append(task_name)
        if version_type != "Delivery":
            parts.append(asset["type"]["name"])
        parts.append(version_number)

        parts = [self.sanitise_for_filesystem(part) for part in parts]

        ### Build base name
        name_parts = []
        name_parts.append(project["name"])
        name_parts.append(task_parent)
        name_parts.append(task_name)
        # name_parts.append(asset["type"]["name"])

        name_parts.append(entity["name"])
        name_parts.append(version_number)

        if version_type == "Delivery":

            name_parts = []
            version_custom_attributes = version["task"]["parent"][
                "custom_attributes"
            ]

            project_game = project["custom_attributes"].get("game")
            var_game_logo = version_custom_attributes.get("game_logo")
            final_game_name = var_game_logo or project_game

            channel = version_custom_attributes.get("channel")

            quota = version_custom_attributes.get("quota")

            prefix = f"{final_game_name[0]}_" if final_game_name else ""
            prefix += f"{channel[0]}_" if channel else ""
            prefix += f"{quota[0]}_" if quota else ""

            if prefix:
                name_parts.append(
                    prefix + self.convert_to_pascal_case(project["name"])
                )
            else:
                name_parts.append(project["name"])

            predef_length = version_custom_attributes.get("length", ["none"])

            custom_id = version_custom_attributes.get("custom_id", "")

            user = version["user"]
            assignments = version["task"]["assignments"]
            if assignments:
                user = assignments[0]["resource"]

            metadata = entity["metadata"]

            resolution = metadata.get("resolution")

            file_length = metadata.get("duration")
            if user:
                name_parts.append(user["first_name"] + user["last_name"])

            if file_length:
                name_parts.append(f"{round(float(file_length))}s")
            else:
                if predef_length and predef_length[0] != "none":
                    name_parts.append(predef_length[0])

            if resolution:
                name_parts.append(resolution)

            if custom_id:
                name_parts.append(
                    f"{custom_id}-{task_name}-{get_resolution_id(resolution)}"
                )

        if version_type == "Texture":
            name_parts = []
            name_parts.append(entity["name"])

        base_name = "_".join(
            [self.sanitise_for_filesystem(name) for name in name_parts]
        )

        return {"parts": parts, "base_name": base_name}

    def _format_version(self, number):
        """Return a formatted string representing version *number*."""
        return "v{0:03d}".format(number)

    def clean_filename(self, filepath):
        # Extract the file name from the path
        filename = os.path.basename(filepath)
        # Remove patterns like .%0Xd.png, _%0Xd.png, or %0Xd.png (any padding value)
        cleaned_name = re.sub(r"(\.|_)?%0\d+d\.[a-zA-Z0-9]+$", "", filename)
        return cleaned_name

    def sanitise_for_filesystem(self, value):
        """Return *value* with illegal filesystem characters replaced.

        An illegal character is one that is not typically valid for filesystem
        usage, such as non ascii characters, or can be awkward to use in a
        filesystem, such as spaces. Replace these characters with
        the character specified by *illegal_character_substitute* on
        initialisation. If no character was specified as substitute then return
        *value* unmodified.

        """
        if self.illegal_character_substitute is None:
            return value

        value = unicodedata.normalize("NFKD", str(value)).encode(
            "ascii", "ignore"
        )
        value = re.sub(
            "[^\w\.-]", self.illegal_character_substitute, value.decode("utf-8")
        )
        return str(value.strip())

    def convert_to_pascal_case(self, value):
        """Convert snake_case string to PascalCase format."""
        return "".join(word.title() for word in value.split("_"))

    def get_resource_identifier(self, entity, context=None):
        """Return a resource identifier for supplied *entity*.

        *context* can be a mapping that supplies additional information, but
        is unused in this implementation.


        Raise a :py:exc:`ftrack_api.exeption.StructureError` if *entity* is not
        attached to a committed version and a committed asset with a parent
        context.

        """

        if entity.entity_type in ("FileComponent",):
            container = entity["container"]

            if container:
                # Get resource identifier for container.
                container_path = self.get_resource_identifier(container)
                container_name = self.clean_filename(container_path)

                if container.entity_type in ("SequenceComponent",):
                    # Strip the sequence component expression from the parent
                    # container and back the correct filename, i.e.
                    # /sequence/component/sequence_component_name.0012.exr.
                    name = "{0}.{1}{2}".format(
                        container_name,
                        entity["name"],
                        entity["file_type"],
                    )
                    parts = [
                        os.path.dirname(container_path),
                        self.sanitise_for_filesystem(name),
                    ]

                else:
                    # Container is not a sequence component so add it as a
                    # normal component inside the container.
                    name = (
                        self._get_parts(entity).get("base_name")
                        + entity["file_type"]
                    )
                    parts = [container_path, self.sanitise_for_filesystem(name)]

            else:
                parts = self._get_parts(entity).get("parts")
                name = (
                    self._get_parts(entity).get("base_name")
                    + entity["file_type"]
                )
                parts.append(self.sanitise_for_filesystem(name))

        elif entity.entity_type in ("SequenceComponent",):
            # Create sequence expression for the sequence component and add it
            # to the parts.
            parts = self._get_parts(entity).get("parts")
            sequence_expression = self._get_sequence_expression(entity)
            parts.append(
                "{0}.{1}{2}".format(
                    self._get_parts(entity).get("base_name"),
                    sequence_expression,
                    entity["file_type"],
                )
            )

        elif entity.entity_type in ("ContainerComponent",):
            # Add the name of the container to the resource identifier parts.
            parts = self._get_parts(entity).get("parts")
            parts.append(
                self.sanitise_for_filesystem(
                    self._get_parts(entity).get("base_name")
                )
            )

        else:
            raise NotImplementedError(
                "Cannot generate resource identifier for unsupported "
                "entity {0!r}".format(entity)
            )

        return self.path_separator.join(parts)


def register(*args, **kwargs):
    """Register templates."""
    return None
