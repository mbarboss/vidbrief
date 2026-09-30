"""Interfaces the pipeline depends on; adapters provide the implementations."""

from typing import Protocol

from vidbrief.domain.models import VideoMetadata
from vidbrief.domain.video import VideoId


class VideoMetadataProvider(Protocol):
    """Looks up information about a video without downloading its media."""

    def fetch_metadata(self, video_id: VideoId) -> VideoMetadata:
        """Return the metadata for ``video_id``.

        Raises:
            VideoUnavailableError: If the video is private, removed or restricted.
            LiveStreamNotSupportedError: If the video is a scheduled stream or premiere.
            ExternalServiceError: If the provider fails or answers unexpectedly.
        """
