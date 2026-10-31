"""Atomic owner-only configuration writes that can be retried after interruption."""
import os
from pathlib import Path
import tempfile
import stat


def ensure_private_directory(path: Path):
    if path.is_symlink():
        raise ValueError("Private directory must not be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    information = path.stat()
    if information.st_uid != os.getuid() or information.st_mode & 0o077:
        raise ValueError("Directory must be owner-private")


def read_private(path: Path, limit: int):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        information = os.fstat(stream.fileno())
        if (not stat.S_ISREG(information.st_mode) or information.st_uid != os.getuid()
                or information.st_mode & 0o077 or information.st_size > limit):
            raise ValueError("Private file ownership, permissions or size invalid")
        value = stream.read(limit + 1)
        if len(value) > limit:
            raise ValueError("Private file size invalid")
        return value


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
