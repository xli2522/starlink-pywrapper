"""Owned POL-2 scratch storage with automatic short path aliases."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile


ADAM_PATH_LIMIT = 132
PREDICTED_SUFFIX = Path(
    "starlink-temp-12345678/NDG_12345678/adam_12345678_py/pol2check.sdf"
)


class ScratchError(RuntimeError):
    pass


class ShortScratch:
    """Create physical scratch under a workspace and expose a short alias."""

    def __init__(
        self,
        workspace: Path,
        *,
        alias_root: Path | None = None,
        path_limit: int = ADAM_PATH_LIMIT,
    ) -> None:
        self.workspace = workspace.expanduser().resolve()
        self.alias_root = (
            Path(alias_root).expanduser().resolve()
            if alias_root is not None
            else Path(tempfile.gettempdir()).resolve()
        )
        self.path_limit = path_limit
        self.physical: Path | None = None
        self.alias: Path | None = None
        self.visible: Path | None = None

    def __enter__(self) -> "ShortScratch":
        if not self.workspace.is_dir() or not os.access(self.workspace, os.W_OK):
            raise ScratchError(f"workspace is not writable: {self.workspace}")
        scratch_root = self.workspace / "scratch"
        scratch_root.mkdir(mode=0o700, exist_ok=True)
        self.physical = Path(
            tempfile.mkdtemp(prefix="pol2-", dir=scratch_root)
        ).resolve()
        visible = self.physical
        if len(str(visible / PREDICTED_SUFFIX)) > self.path_limit:
            if (
                not self.alias_root.is_dir()
                or not os.access(self.alias_root, os.W_OK)
            ):
                self.cleanup()
                raise ScratchError(
                    f"short-alias directory is not writable: {self.alias_root}"
                )
            reserved = Path(
                tempfile.mkdtemp(prefix="p2-", dir=self.alias_root)
            )
            reserved.rmdir()
            try:
                reserved.symlink_to(self.physical, target_is_directory=True)
            except BaseException:
                self.cleanup()
                raise
            self.alias = reserved
            visible = reserved
        if len(str(visible / PREDICTED_SUFFIX)) > self.path_limit:
            self.cleanup()
            raise ScratchError(
                f"cannot satisfy Starlink {self.path_limit}-character ADAM path limit"
            )
        self.visible = visible
        return self

    def environment(self) -> dict[str, str]:
        if self.visible is None:
            raise ScratchError("scratch context is not active")
        return {"TMPDIR": str(self.visible)}

    def cleanup(self) -> None:
        alias, physical = self.alias, self.physical
        self.alias = None
        self.visible = None
        self.physical = None
        if alias is not None:
            if not alias.is_symlink():
                raise ScratchError(f"refusing to remove non-symlink alias: {alias}")
            alias.unlink()
        if physical is not None and physical.exists():
            shutil.rmtree(physical)

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.cleanup()
