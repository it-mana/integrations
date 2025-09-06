# :coding: utf-8
# :copyright: Copyright (c) 2025 Mana


import os
import re
import shutil

from setuptools import Command, find_packages, setup

ROOT_PATH = os.path.dirname(os.path.realpath(__file__))
BUILD_PATH = os.path.join(ROOT_PATH, "dist")
SOURCE_PATH = os.path.join(ROOT_PATH, "source")
README_PATH = os.path.join(ROOT_PATH, "README.md")
RESOURCE_PATH = os.path.join(ROOT_PATH, "resource")


# Read version from source.
with open(
    os.path.join(SOURCE_PATH, "ftrack_connect_mana_location", "_version.py"),
) as _version_file:
    VERSION = re.search(
        r"__version__\s*=\s*['\"](.*?)['\"]", _version_file.read()
    ).group(1)


STAGING_PATH = os.path.join(
    BUILD_PATH, "ftrack-connect-mana-location-{0}".format(VERSION)
)


class BuildPlugin(Command):
    """Build plugin."""

    description = "Download dependencies and build plugin ."

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        """Run the build step."""
        # Clean staging path
        shutil.rmtree(STAGING_PATH, ignore_errors=True)

        shutil.copytree(
            RESOURCE_PATH,
            STAGING_PATH,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

        result_path = shutil.make_archive(
            os.path.join(
                BUILD_PATH, "ftrack-connect-mana-location-{0}".format(VERSION)
            ),
            "zip",
            STAGING_PATH,
        )

        shutil.rmtree(
            os.path.join(
                BUILD_PATH, "ftrack-connect-mana-location-{0}".format(VERSION)
            ),
            ignore_errors=True,
        )


# Call main setup.
setup(
    name="ftrack-connect-mana-location",
    version=VERSION,
    description="ftrack mana location plugin.",
    long_description=open(README_PATH).read(),
    keywords="ftrack, integration, connect, location, structure",
    packages=find_packages(SOURCE_PATH),
    package_dir={"": "source"},
    zip_safe=False,
    cmdclass={
        "build_plugin": BuildPlugin,
    },
    python_requires=">=3, < 4.0",
)
