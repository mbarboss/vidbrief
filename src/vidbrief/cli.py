"""Command-line entry point: summarize one video as Markdown or start the web interface."""

import argparse
import logging
import sys
from collections.abc import Callable, Iterable, Sequence
from typing import Protocol, TextIO

from pydantic import ValidationError
from starlette.types import ASGIApp

from vidbrief.composition import build_pipeline
from vidbrief.config import LogLevel, Settings, get_settings
from vidbrief.domain.errors import VidbriefError
from vidbrief.domain.languages import SUPPORTED_SUMMARY_LANGUAGES
from vidbrief.domain.progress import Progress
from vidbrief.domain.video import parse_youtube_url
from vidbrief.logging_config import configure_logging
from vidbrief.services.pipeline import SummaryRunner
from vidbrief.services.progress_text import STAGE_LABELS, describe
from vidbrief.services.report import to_markdown
from vidbrief.web.app import create_app
from vidbrief.web.server import Server, run_server, server_url

logger = logging.getLogger(__name__)

_EXIT_FAILURE = 1
_EXIT_CONFIG_ERROR = 2
_EXIT_INTERRUPTED = 130


class AppFactory(Protocol):
    def __call__(self, settings: Settings, runner: SummaryRunner) -> ASGIApp: ...


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
    create_app: AppFactory = create_app,
    serve: Server = run_server,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run ``vidbrief URL`` or ``vidbrief serve`` and return the process exit status.

    ``vidbrief URL`` prints the Markdown summary to ``stdout`` and progress to ``stderr``,
    so the output can be redirected to a file; only errors are logged unless ``--verbose``
    is passed. ``vidbrief serve`` starts the web interface on the configured loopback
    address and logs at ``VIDBRIEF_LOG_LEVEL``.
    """
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    args = list(sys.argv[1:] if argv is None else argv)
    # A video link can never be the word "serve", so it safely selects the subcommand
    # without breaking the original ``vidbrief URL`` form.
    if args[:1] == ["serve"]:
        _serve_parser().parse_args(args[1:])
        settings = _load_settings(load_settings, err)
        if settings is None:
            return _EXIT_CONFIG_ERROR
        setup_logging(settings.log_level, secrets=[settings.groq_api_key.get_secret_value()])
        return _serve(settings, build, create_app, serve, err)

    options = _parser().parse_args(args)
    settings = _load_settings(load_settings, err)
    if settings is None:
        return _EXIT_CONFIG_ERROR
    setup_logging(
        settings.log_level if options.verbose else "ERROR",
        secrets=[settings.groq_api_key.get_secret_value()],
    )
    return _summarize(options.url, options.language, settings, build, out, err)


def _load_settings(load: Callable[[], Settings], err: TextIO) -> Settings | None:
    try:
        return load()
    except ValidationError as error:
        # Input values are hidden by the settings model, so only field names are shown.
        fields = sorted({".".join(str(part) for part in item["loc"]) for item in error.errors()})
        print(f"Configuration error in: {', '.join(fields)}. Check your .env file.", file=err)
        return None


def _summarize(
    url: str,
    language: str | None,
    settings: Settings,
    build: Callable[[Settings], SummaryRunner],
    out: TextIO,
    err: TextIO,
) -> int:
    def show(progress: Progress) -> None:
        if progress.stage in STAGE_LABELS and progress.video is None:
            print(f"{describe(progress)}...", file=err, flush=True)

    try:
        video_id = parse_youtube_url(url)
        result = build(settings).run(
            video_id, language or settings.default_summary_language, on_progress=show
        )
    except VidbriefError as error:
        logger.warning("summary failed", extra={"reason": error.reason})
        print(f"Error: {error.user_message}", file=err)
        if error.user_hint:
            print(error.user_hint, file=err)
        return _EXIT_FAILURE
    except KeyboardInterrupt:
        print("Cancelled.", file=err)
        return _EXIT_INTERRUPTED

    out.write(to_markdown(result))
    return 0


def _serve(
    settings: Settings,
    build: Callable[[Settings], SummaryRunner],
    create_app: AppFactory,
    serve: Server,
    err: TextIO,
) -> int:
    try:
        # Building the pipeline first makes a missing ffmpeg or Deno stop the server at
        # startup instead of failing the first summary.
        runner = build(settings)
    except VidbriefError as error:
        logger.warning("server not started", extra={"reason": error.reason})
        print(f"Error: {error.user_message}", file=err)
        return _EXIT_FAILURE

    url = server_url(settings.host, settings.port)
    print(f"vidbrief is running at {url} (press Ctrl+C to stop)", file=err, flush=True)
    serve(create_app(settings, runner), host=settings.host, port=settings.port)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vidbrief",
        description="Summarize a YouTube video with AI.",
        epilog="Run 'vidbrief serve' to open the web interface instead.",
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


def _serve_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="vidbrief serve",
        description="Start the web interface on VIDBRIEF_HOST and VIDBRIEF_PORT.",
    )
