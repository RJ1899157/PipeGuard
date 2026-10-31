"""Atomic owner-only configuration writes that can be retried after interruption."""
import os
from pathlib import Path
import tempfile


def write_private(path: Path, content: str, *, exclusive: bool = False):
    if path.is_symlink():
        raise ValueError("Private configuration must be a regular file")
    descriptor, temporary_name = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
        temporary.unlink(missing_ok=True)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
