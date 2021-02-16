#!/usr/bin/env python
from setuptools import setup, Command
import os

__doc__ = """
Command line tool and library wrappers around iwlist and
/etc/network/interfaces.
"""


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


install_requires = ["setuptools", "pbkdf2", "netaddr"]
try:
    import argparse
except:
    install_requires.append("argparse")

version = "1.1.0"

EXTRAS = [
    (
        "/etc/bash_completion.d/",
        [("extras/wifi-completion.bash", "wifi-completion", 0o644)],
    )
]


def get_extra_tuple(entry):
    if isinstance(entry, (tuple, list)):
        if len(entry) == 2:
            path, mode = entry
            filename = os.path.basename(path)
        elif len(entry) == 3:
            path, filename, mode = entry
        elif len(entry) == 1:
            path = entry[0]
            filename = os.path.basename(path)
            mode = None
        else:
            return None

    else:
        path = entry
        filename = os.path.basename(path)
        mode = None

    return path, filename, mode


class InstallExtrasCommand(Command):
    description = "install extras like init scripts and config files"
    user_options = [("force", "F", "force overwriting files if they already exist")]

    def initialize_options(self):
        self.force = None

    def finalize_options(self):
        if self.force is None:
            self.force = False

    def run(self):
        global EXTRAS
        import shutil
        import os

        for target, files in EXTRAS:
            for entry in files:
                extra_tuple = get_extra_tuple(entry)
                if extra_tuple is None:
                    print(
                        "Can't parse entry for target %s, skipping it: %r"
                        % (target, entry)
                    )
                    continue

                path, filename, mode = extra_tuple
                target_path = os.path.join(target, filename)

                path_exists = os.path.exists(target_path)
                if path_exists and not self.force:
                    print(
                        "Skipping copying %s to %s as it already exists, use --force to overwrite"
                        % (path, target_path)
                    )
                    continue

                try:
                    shutil.copy(path, target_path)
                    if mode:
                        os.chmod(target_path, mode)
                        print(
                            "Copied %s to %s and changed mode to %o"
                            % (path, target_path, mode)
                        )
                    else:
                        print("Copied %s to %s" % (path, target_path))
                except Exception as e:
                    if not path_exists and os.path.exists(target_path):
                        # we'll try to clean up again
                        try:
                            os.remove(target_path)
                        except:
                            pass

                    import sys

                    print(
                        "Error while copying %s to %s (%s), aborting"
                        % (path, target_path, e.message)
                    )
                    sys.exit(-1)


class UninstallExtrasCommand(Command):
    description = "uninstall extras like init scripts and config files"
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        global EXTRAS
        import os

        for target, files in EXTRAS:
            for entry in files:
                extra_tuple = get_extra_tuple(entry)
                if extra_tuple is None:
                    print(
                        "Can't parse entry for target %s, skipping it: %r"
                        % (target, entry)
                    )

                path, filename, mode = extra_tuple
                target_path = os.path.join(target, filename)
                try:
                    os.remove(target_path)
                    print("Removed %s" % target_path)
                except Exception as e:
                    print(
                        "Error while deleting %s from %s (%s), please remove manually"
                        % (filename, target, e.message)
                    )


setup(
    name="wifi",
    version=version,
    author="Rocky Meza, Gavin Wahl",
    author_email="rockymeza@gmail.com",
    description=__doc__,
    long_description="\n\n".join([read("README.rst"), read("CHANGES.rst")]),
    packages=["wifi"],
    scripts=["bin/wifi"],
    test_suite="tests",
    platforms=["Debian"],
    license="BSD",
    install_requires=install_requires,
    classifiers=[
        "License :: OSI Approved :: BSD License",
        "Topic :: System :: Networking",
        "Operating System :: POSIX :: Linux",
        "Environment :: Console",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2.6",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3.3",
    ],
    cmdclass={
        "install_extras": InstallExtrasCommand,
        "uninstall_extras": UninstallExtrasCommand,
    },
)
