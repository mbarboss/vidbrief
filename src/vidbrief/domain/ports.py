"""Interfaces the pipeline depends on; adapters provide the implementations."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from vidbrief.domain.models import AudioChunk, CaptionTrack, Transcript, VideoMetadata
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


class AudioProvider(Protocol):
    """Prepares a video's audio as files ready for speech-to-text."""

    def prepare_audio(self, video_id: VideoId) -> AbstractContextManager[Sequence[AudioChunk]]:
        """Return a context manager yielding the audio chunks in playback order.

        The files exist only inside the ``with`` block and are deleted when it exits,
        including when it exits with an exception.

        Raises:
            AudioProcessingError: If the audio cannot be downloaded, converted or split.
            VideoUnavailableError: If the video cannot be accessed.
            ExternalServiceError: If YouTube refuses or fails the download.
        """
