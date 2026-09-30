"""Command-line entry point: summarize one video and print the result as Markdown."""

import argparse
import logging
import sys
from collections.abc import Callable, Iterable, Sequence
from typing import Protocol, TextIO

from pydantic import ValidationError

from vidbrief.composition import build_pipeline
from vidbrief.config import LogLevel, Settings, get_settings
from vidbrief.domain.errors import VidbriefError
from vidbrief.domain.languages import SUPPORTED_SUMMARY_LANGUAGES
from vidbrief.domain.progress import PipelineStage, Progress
from vidbrief.domain.video import parse_youtube_url
from vidbrief.logging_config import configure_logging
from vidbrief.services.pipeline import SummaryRunner
from vidbrief.services.report import to_markdown

logger = logging.getLogger(__name__)

_STAGE_LABELS = {
    PipelineStage.CHECKING_VIDEO: "Checking the video",
    PipelineStage.FETCHING_CAPTIONS: "Fetching captions",
    PipelineStage.PREPARING_AUDIO: "Downloading and converting the audio",
    PipelineStage.TRANSCRIBING: "Transcribing the audio",
    PipelineStage.SUMMARIZING: "Summarizing",
}
_EXIT_FAILURE = 1
_EXIT_CONFIG_ERROR = 2
_EXIT_INTERRUPTED = 130


class LoggingSetup(Protocol):
    def __call__(
        self, level: LogLevel, *, secrets: Iterable[str] = (), stream: TextIO | None = None
    ) -> None: ...


def main(
    argv: Sequence[str] | None = None,
    *,
    load_settings: Callable[[], Settings] = get_settings,
    build: Callable[[Settings], SummaryRunner] = build_pipeline,
    setup_logging: LoggingSetup = configure_logging,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Summarize the video given in ``argv`` and return the process exit status.

    Progress goes to ``stderr`` and the Markdown summary to ``stdout``, so the output can
    be redirected to a file. Only errors are logged unless ``--verbose`` is passed.
    """
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    args = _parser().parse_args(argv)

    try:
        settings = load_settings()
    except ValidationError as error:
        # Input values are hidden by the settings model, so only field names are shown.
        fields = sorted({".".join(str(part) for part in item["loc"]) for item in error.errors()})
        print(f"Configuration error in: {', '.join(fields)}. Check your .env file.", file=err)
        return _EXIT_CONFIG_ERROR

    setup_logging(
        settings.log_level if args.verbose else "ERROR",
        secrets=[settings.groq_api_key.get_secret_value()],
    )
    language = args.language or settings.default_summary_language

    def show(progress: Progress) -> None:
        if progress.stage in _STAGE_LABELS:
            print(f"{_describe(progress)}...", file=err, flush=True)

    try:
        video_id = parse_youtube_url(args.url)
        result = build(settings).run(video_id, language, on_progress=show)
    except VidbriefError as error:
        logger.warning("summary failed", extra={"reason": error.reason})
        print(f"Error: {error.user_message}", file=err)
        return _EXIT_FAILURE
    except KeyboardInterrupt:
        print("Cancelled.", file=err)
        return _EXIT_INTERRUPTED

    out.write(to_markdown(result))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vidbrief", description="Summarize a YouTube video with AI."
    )
    parser.add_argument("url", help="a YouTube video link")
    parser.add_argument(
        "--language",
        choices=sorted(SUPPORTED_SUMMARY_LANGUAGES),
        help="summary language (default: VIDBRIEF_DEFAULT_SUMMARY_LANGUAGE)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="show JSON logs at VIDBRIEF_LOG_LEVEL"
    )
    return parser


def _describe(progress: Progress) -> str:
    label = _STAGE_LABELS[progress.stage]
    if progress.step is None or progress.total is None:
        return label
    # Summary totals are re-estimated as the token budget is learned.
    approx = "~" if progress.stage is PipelineStage.SUMMARIZING else ""
    return f"{label} ({progress.step}/{approx}{progress.total})"
