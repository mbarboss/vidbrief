"""Interfaces the pipeline depends on; adapters provide the implementations."""

from typing import Protocol

from vidbrief.domain.models import CaptionTrack, Transcript, VideoMetadata
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


class CaptionProvider(Protocol):
    """Downloads one caption track and turns it into a transcript."""

    def fetch_captions(self, video_id: VideoId, track: CaptionTrack) -> Transcript:
        """Return the transcript built from ``track``.

        Raises:
            CaptionsUnavailableError: If the track cannot be downloaded or has no speech;
                callers are expected to fall back to transcribing the audio.
        """
