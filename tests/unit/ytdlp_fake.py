"""Test double for ``yt_dlp.YoutubeDL`` shared by the yt-dlp adapter tests."""

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self


class FakeYoutubeDL:
    """Stands in for both the ``YoutubeDL`` class (when called) and its instances.

    When ``extract_info`` runs with ``download=True``, every entry in ``files`` is written
    into the ``paths.home`` directory from the options, mimicking yt-dlp's output.
    """

    def __init__(
        self,
        outcome: dict[str, Any] | Exception | None = None,
        *,
        files: Mapping[str, bytes] = MappingProxyType({}),
    ) -> None:
        self.outcome = outcome
        self.files = files
        self.options: dict[str, Any] = {}
        self.extracted: list[tuple[str, bool]] = []

    def __call__(self, options: dict[str, Any]) -> Self:
        self.options = options
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    @property
    def workdir(self) -> Path:
        return Path(self.options["paths"]["home"])

    def extract_info(self, url: str, download: bool) -> Any:
        self.extracted.append((url, download))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if download:
            for name, content in self.files.items():
                (self.workdir / name).write_bytes(content)
        return self.outcome
