"""Tests for the pieces shared by every yt-dlp adapter."""

import logging

import pytest

from vidbrief.adapters.ytdlp_common import YtDlpLogger, base_options


def test_base_options_are_safe() -> None:
    options = base_options(socket_timeout_seconds=12.5)

    assert options["skip_download"] is True
    assert options["noplaylist"] is True
    assert options["quiet"] is True
    assert options["socket_timeout"] == 12.5
    assert isinstance(options["logger"], YtDlpLogger)
    assert "cookiefile" not in options
    assert "cookiesfrombrowser" not in options


def test_base_options_are_independent_copies() -> None:
    first = base_options(socket_timeout_seconds=1.0)
    first["noplaylist"] = False

    assert base_options(socket_timeout_seconds=1.0)["noplaylist"] is True


def test_logger_routes_ytdlp_output_to_logging(caplog: pytest.LogCaptureFixture) -> None:
    ytdlp_logger = YtDlpLogger()

    with caplog.at_level(logging.DEBUG, logger="vidbrief.adapters.ytdlp"):
        ytdlp_logger.debug("debug line")
        ytdlp_logger.info("info line")
        ytdlp_logger.warning("warning line")
        ytdlp_logger.error("error line")

    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (logging.DEBUG, "debug line"),
        (logging.DEBUG, "info line"),
        (logging.WARNING, "warning line"),
        (logging.ERROR, "error line"),
    ]
