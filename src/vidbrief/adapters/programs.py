"""Lookup of the external programs vidbrief relies on."""

import shutil

from vidbrief.domain.errors import MissingDependencyError


def find_program(name: str) -> str:
    """Return the full path of the executable ``name`` found on ``PATH``.

    Raises:
        MissingDependencyError: If ``name`` is not installed or not on ``PATH``.
    """
    path = shutil.which(name)
    if path is None:
        raise MissingDependencyError(name)
    return path
