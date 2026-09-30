"""Tests for the audio provider that ties download, conversion and splitting together."""

from pathlib import Path

import pytest

from vidbrief.adapters.local_audio import LocalAudioProvider
from vidbrief.domain.errors import AudioProcessingError
from vidbrief.domain.models import AudioChunk
from vidbrief.domain.ports import AudioProvider
from vidbrief.domain.video import VideoId

VIDEO_ID = VideoId("jNQXAC9IVRw")


class FakeDownloader:
    def __init__(self) -> None:
        self.workdirs: list[Path] = []

    def download(self, video_id: VideoId, workdir: Path) -> Path:
        self.workdirs.append(workdir)
        source = workdir / f"{video_id.value}.source.webm"
        source.write_bytes(b"original audio")
        return source


class FakeProcessor:
    def __init__(self, *, chunk_count: int = 1, fail_on: str | None = None) -> None:
        self.chunk_count = chunk_count
        self.fail_on = fail_on
        self.normalized: list[tuple[Path, Path]] = []
        self.source_existed_at_split: bool | None = None
        self.max_bytes: int | None = None

    def normalize(self, source: Path, destination: Path) -> None:
        if self.fail_on == "normalize":
            raise AudioProcessingError("command_failed")
        self.normalized.append((source, destination))
        destination.write_bytes(b"normalized audio")

    def split(self, path: Path, max_bytes: int) -> list[Path]:
        if self.fail_on == "split":
            raise AudioProcessingError("chunk_too_large")
        self.max_bytes = max_bytes
        source, _ = self.normalized[-1]
        self.source_existed_at_split = source.exists()
        if self.chunk_count == 1:
            return [path]
        chunks = [path.with_name(f"chunk{index}.ogg") for index in range(self.chunk_count)]
        for chunk in chunks:
            chunk.write_bytes(b"chunk")
        return chunks


def _provider(processor: FakeProcessor, downloader: FakeDownloader) -> LocalAudioProvider:
    return LocalAudioProvider(downloader=downloader, processor=processor, max_chunk_bytes=1000)


def test_satisfies_the_audio_port() -> None:
    provider: AudioProvider = _provider(FakeProcessor(), FakeDownloader())

    assert provider is not None


def test_yields_numbered_chunks_that_exist_inside_the_block() -> None:
    downloader = FakeDownloader()
    processor = FakeProcessor(chunk_count=3)

    with _provider(processor, downloader).prepare_audio(VIDEO_ID) as chunks:
        assert [chunk.index for chunk in chunks] == [0, 1, 2]
        assert all(chunk.path.exists() for chunk in chunks)
        assert all(chunk.path.parent == downloader.workdirs[0] for chunk in chunks)

    assert processor.max_bytes == 1000


def test_normalizes_into_a_file_named_after_the_video() -> None:
    downloader = FakeDownloader()
    processor = FakeProcessor()

    with _provider(processor, downloader).prepare_audio(VIDEO_ID) as chunks:
        [(source, destination)] = processor.normalized
        assert source == downloader.workdirs[0] / f"{VIDEO_ID.value}.source.webm"
        assert destination == downloader.workdirs[0] / f"{VIDEO_ID.value}.ogg"
        assert chunks == (AudioChunk(index=0, path=destination),)


def test_deletes_the_original_download_before_splitting() -> None:
    processor = FakeProcessor()

    with _provider(processor, FakeDownloader()).prepare_audio(VIDEO_ID):
        pass

    assert processor.source_existed_at_split is False


def test_removes_every_file_after_the_block() -> None:
    downloader = FakeDownloader()

    with _provider(FakeProcessor(chunk_count=2), downloader).prepare_audio(VIDEO_ID):
        pass

    assert not downloader.workdirs[0].exists()


def test_removes_every_file_when_the_block_raises() -> None:
    downloader = FakeDownloader()

    with (
        pytest.raises(RuntimeError),
        _provider(FakeProcessor(), downloader).prepare_audio(VIDEO_ID),
    ):
        raise RuntimeError("transcription failed")

    assert not downloader.workdirs[0].exists()


@pytest.mark.parametrize("step", ["normalize", "split"])
def test_removes_every_file_when_processing_fails(step: str) -> None:
    downloader = FakeDownloader()
    provider = _provider(FakeProcessor(fail_on=step), downloader)

    with pytest.raises(AudioProcessingError), provider.prepare_audio(VIDEO_ID):
        pass

    assert not downloader.workdirs[0].exists()
