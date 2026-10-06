# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-05

### Added

- Docker image with Python, ffmpeg and Deno bundled, plus a `compose.yaml` that publishes
  the app on `127.0.0.1:8000` only and runs it as an unprivileged user on a read-only
  filesystem with all capabilities dropped.
- `VIDBRIEF_CONTAINER` setting: in container mode the server may bind `0.0.0.0`, which
  Docker needs to deliver published ports; any other non-loopback address is still
  refused, and only loopback host names are answered.
- CI builds the image and checks that the container starts healthy, serves the home page,
  rejects unknown host names and runs as a non-root user.
- Dependabot proposes updates to the digest-pinned base images.

## [0.1.0] - 2026-10-05

First release: summarize YouTube videos locally from the browser or the command line.

### Added

- Accept watch, short (`youtu.be`), Shorts, live and embed links, with or without a scheme,
  and reject anything that is not a YouTube video
  ([#1](https://github.com/mbarboss/vidbrief/pull/1)).
- Check the video before doing any work: live, upcoming and just-ended streams are refused,
  and so are videos longer than `VIDBRIEF_MAX_VIDEO_DURATION_SECONDS` (2 hours by default)
  ([#2](https://github.com/mbarboss/vidbrief/pull/2)).
- Use the video's own captions when they exist, preferring manual captions in the spoken
  language, then YouTube's automatic captions, never machine translations
  ([#3](https://github.com/mbarboss/vidbrief/pull/3)).
- Fall back to downloading only the audio, converting it to a small mono file with ffmpeg
  and splitting it to stay under `VIDBRIEF_AUDIO_CHUNK_MAX_MB`
  ([#4](https://github.com/mbarboss/vidbrief/pull/4)), then transcribing it with Groq
  Whisper ([#5](https://github.com/mbarboss/vidbrief/pull/5)).
- Summarize into a TL;DR and 3 to 10 key points in Brazilian Portuguese, English, Spanish,
  French, German, Italian, Japanese or Simplified Chinese. Long transcripts are split so
  every request fits the Groq free tier's per-minute token limit
  ([#6](https://github.com/mbarboss/vidbrief/pull/6)).
- Retry Groq requests on timeouts and server errors, and wait when Groq asks to slow down
  ([#5](https://github.com/mbarboss/vidbrief/pull/5),
  [#6](https://github.com/mbarboss/vidbrief/pull/6)).
- `vidbrief URL [--language CODE] [--verbose]` prints progress to stderr and the summary as
  Markdown to stdout ([#7](https://github.com/mbarboss/vidbrief/pull/7)).
- `vidbrief serve` starts the web app on `http://127.0.0.1:8000`
  ([#10](https://github.com/mbarboss/vidbrief/pull/10)) with a home page to paste a link and
  choose the language ([#11](https://github.com/mbarboss/vidbrief/pull/11)).
- Summaries run in the background with live progress for each step, timings and request
  counters ([#12](https://github.com/mbarboss/vidbrief/pull/12)).
- Copy the finished summary as Markdown or download it as a `.md` file
  ([#13](https://github.com/mbarboss/vidbrief/pull/13)).
- Failures are explained in plain words with a hint, and "Try again" is offered when
  waiting may help ([#14](https://github.com/mbarboss/vidbrief/pull/14)).
- Light and dark themes, phone layout, and pages that work without JavaScript
  ([#11](https://github.com/mbarboss/vidbrief/pull/11),
  [#13](https://github.com/mbarboss/vidbrief/pull/13)).
- Startup checks that name a missing Deno, ffmpeg or ffprobe
  ([#9](https://github.com/mbarboss/vidbrief/pull/9)).
- Structured JSON logs on stderr ([#1](https://github.com/mbarboss/vidbrief/pull/1)).
- Cross-platform tasks (`uv run poe ...`) and CI on Linux, macOS and Windows with Python
  3.12 and 3.14 ([#8](https://github.com/mbarboss/vidbrief/pull/8)).
- README with features, screenshots, pipeline and architecture diagrams
  ([#15](https://github.com/mbarboss/vidbrief/pull/15)).

### Security

- Only canonical `https://www.youtube.com/watch?v=<id>` URLs rebuilt from the video ID
  reach yt-dlp; the link the user typed is never passed on
  ([#1](https://github.com/mbarboss/vidbrief/pull/1)).
- No shell is ever used: yt-dlp runs through its Python API and ffmpeg receives argument
  lists limited to the `file:` protocol
  ([#4](https://github.com/mbarboss/vidbrief/pull/4)).
- Downloads are capped in size, kept in temporary directories named by video ID and
  deleted afterwards ([#3](https://github.com/mbarboss/vidbrief/pull/3),
  [#4](https://github.com/mbarboss/vidbrief/pull/4)).
- Transcripts are treated as untrusted data in prompts, and captions too long for the
  video's length are ignored ([#6](https://github.com/mbarboss/vidbrief/pull/6),
  [#9](https://github.com/mbarboss/vidbrief/pull/9)).
- The Groq API key and anything that looks like one are redacted from logs
  ([#1](https://github.com/mbarboss/vidbrief/pull/1),
  [#9](https://github.com/mbarboss/vidbrief/pull/9)).
- The web app binds to loopback only and checks the `Host` header, the request origin and
  a CSRF token on every form ([#10](https://github.com/mbarboss/vidbrief/pull/10)).
- Strict Content Security Policy, no inline scripts, vendored assets pinned with
  Subresource Integrity, and model output sanitized before it is shown
  ([#11](https://github.com/mbarboss/vidbrief/pull/11),
  [#13](https://github.com/mbarboss/vidbrief/pull/13)).
- Limits on concurrent and stored jobs ([#12](https://github.com/mbarboss/vidbrief/pull/12)).

[Unreleased]: https://github.com/mbarboss/vidbrief/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/mbarboss/vidbrief/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mbarboss/vidbrief/releases/tag/v0.1.0
