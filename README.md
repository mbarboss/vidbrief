# vidbrief

[![CI](https://github.com/mbarboss/vidbrief/actions/workflows/ci.yml/badge.svg)](https://github.com/mbarboss/vidbrief/actions/workflows/ci.yml)

> Paste a YouTube link and get a concise AI-generated summary in your language.

**Status:** 🚧 Work in progress (MVP under development)

## Features (planned)

- [ ] Paste a YouTube URL and preview title, thumbnail and duration
- [ ] Choose the summary language
- [ ] Captions-first strategy: uses existing captions when available, falling back to audio transcription
- [ ] Speech-to-text via Groq Whisper, with automatic chunking for long videos
- [ ] TL;DR + key points summary via Groq LLM (map-reduce for long transcripts)
- [ ] Real-time progress updates (Server-Sent Events)
- [ ] Copy summary or download it as Markdown

## How it works

```
YouTube URL ─► validate ─► captions? ──yes──────────────────────┐
                              │                                 ▼
                              no ─► download audio ─► transcribe ─► summarize ─► result
```

### Which captions are used

When a video has captions, vidbrief picks one track in this order and only transcribes the
audio when none fits:

1. Captions written by the uploader in the spoken language.
2. YouTube's automatic speech recognition in the spoken language.
3. Captions written by the uploader in another language (English first).

Machine-translated automatic captions are never used; the summarizer translates from the
original text instead. Sound-only cues such as `[Music]` or `[Applause]` are dropped.
Captions longer than the video could plausibly hold (more than 40 characters per second)
are ignored and the audio is transcribed instead, so a crafted caption file cannot turn
one summary into thousands of billed requests.

### Audio fallback

Without usable captions, vidbrief downloads only the audio stream (never the video) and
converts it to 24 kbps mono Opus, which keeps speech clear for Whisper at about 10 MB per
hour. Recordings larger than `VIDBRIEF_AUDIO_CHUNK_MAX_MB` are split by time into chunks;
with the defaults (24 MB, videos up to 2 hours) the whole audio always fits in one
request, and splitting only kicks in if you lower the chunk size or raise the duration
limit.
All files live in a temporary folder that is deleted as soon as the job ends, even when
it fails.

### Transcription

The audio chunks are sent one at a time to Groq's Whisper model
(`VIDBRIEF_TRANSCRIPTION_MODEL`), with the video's spoken language as a hint when YouTube
reports it. The last words of each chunk are passed along with the next one so sentences
cut at a chunk boundary stay coherent.

Timeouts, connection errors and server errors are retried up to three times per chunk.
When Groq's rate limit asks for a wait of up to a minute, vidbrief waits and retries;
longer waits (for example, when the free tier's hourly audio quota is used up) end the job
with a "try again later" message instead of blocking it.

On Groq's free tier, speech-to-text is limited to 2 hours of audio per hour and 8 hours
per day, so only a few long videos without captions can be transcribed each day. Videos
with captions do not use this quota.

### Summary

The transcript is summarized by a Groq chat model (`VIDBRIEF_SUMMARY_MODEL`) into a TL;DR
and 3 to 10 key points, in the language you choose. The model must support strict
structured outputs (currently `openai/gpt-oss-120b`, `openai/gpt-oss-20b` and
`qwen/qwen3.8-27b` on Groq).

Groq limits how many tokens each API key can use per minute, counting the prompt plus the
longest answer a request allows. vidbrief therefore sizes every request to that limit:

- A transcript that fits in one request is summarized directly.
- A longer one is cut into chunks (at sentence ends when possible); each chunk becomes
  short notes, and the notes are summarized. Notes that are still too long are condensed
  again first.
- The first request uses a size that fits the free tier. After that, vidbrief reads the
  limit Groq reports in every response and uses 75% of it (up to 32,000 tokens per request),
  so paid plans automatically get fewer, larger requests. To pin the size instead, set
  `VIDBRIEF_SUMMARY_MAX_REQUEST_TOKENS`.

Measured on the free tier: a 57-minute lecture with captions was summarized in 74 seconds
(six requests, including four short waits for the per-minute token limit), and a
13-minute talk without usable captions took 15 seconds end to end (download and
conversion 10 s, Whisper 3 s, summary 1 s). Expect roughly one to two minutes per hour of
captioned video; paid plans are faster.

## Supported links

Only video links on YouTube's own hosts are accepted; the `https://` prefix is optional and
extra parameters such as `t=`, `list=` or `si=` are ignored.

| Format | Example |
|---|---|
| Watch page | `https://www.youtube.com/watch?v=dQw4w9WgXcQ` |
| Short link | `https://youtu.be/dQw4w9WgXcQ` |
| Shorts | `https://www.youtube.com/shorts/dQw4w9WgXcQ` |
| Live | `https://www.youtube.com/live/dQw4w9WgXcQ` |
| Embed | `https://www.youtube.com/embed/dQw4w9WgXcQ` |

Accepted hosts: `youtube.com`, `www.youtube.com`, `m.youtube.com`, `youtu.be` and
`www.youtube-nocookie.com`. Playlists and channel pages are not supported.

### Videos that cannot be summarized

- Live streams that are in progress, scheduled or still being processed (finished streams
  work normally).
- Private, removed, region-blocked, age-restricted or members-only videos. vidbrief never
  uses your YouTube/Google login cookies, so restricted content stays out of reach by design.
- Videos longer than `VIDBRIEF_MAX_VIDEO_DURATION_SECONDS` (2 hours by default), or whose
  length YouTube does not report.

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.12, managed with [uv](https://docs.astral.sh/uv/) |
| Web | FastAPI, Jinja2, HTMX, Server-Sent Events |
| Media | yt-dlp (+ Deno JS runtime), ffmpeg |
| AI | Groq API (Whisper for speech-to-text, GPT-OSS for summarization) |
| Quality | Ruff, mypy (strict), pytest, pre-commit, poethepoet, GitHub Actions |
| Security | Ruff security rules (Bandit), detect-secrets, pip-audit |

## Prerequisites

vidbrief runs on Linux, macOS and Windows; every change is tested on all three by CI
(Ubuntu, macOS and Windows with Python 3.12 and 3.14).

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (installs Python for you)
- [ffmpeg](https://ffmpeg.org/) (audio conversion)
- [Deno](https://deno.com/) (required by yt-dlp for YouTube)
- A [Groq API key](https://console.groq.com/keys)

| System | Install the tools |
|---|---|
| Ubuntu / Debian | `sudo apt install ffmpeg`, then `curl -LsSf https://astral.sh/uv/install.sh \| sh` and `curl -fsSL https://deno.land/install.sh \| sh` |
| macOS ([Homebrew](https://brew.sh/)) | `brew install uv ffmpeg deno` |
| Windows (winget) | `winget install astral-sh.uv Gyan.FFmpeg DenoLand.Deno` |
| Windows ([Chocolatey](https://chocolatey.org/)) | `choco install ffmpeg deno`, plus uv with winget or its [installer](https://docs.astral.sh/uv/getting-started/installation/) |

Open a new terminal afterwards so the tools are on your `PATH`. vidbrief checks for
ffmpeg, ffprobe and Deno at startup and names whichever one is missing.

## Getting started

```bash
git clone https://github.com/mbarboss/vidbrief.git
cd vidbrief
uv run poe install
```

Then create your `.env` from the example and set `GROQ_API_KEY` in it:

```bash
cp .env.example .env && chmod 600 .env    # Linux and macOS
Copy-Item .env.example .env               # Windows (PowerShell)
```

### Command line

Until the web interface is ready, videos can be summarized from the terminal:

```bash
uv run vidbrief "https://youtu.be/jNQXAC9IVRw" --language pt-BR
uv run vidbrief "https://youtu.be/jNQXAC9IVRw" > summary.md   # save to a file
```

Progress is shown on stderr (for example `Transcribing the audio (2/5)...` or
`Summarizing (3/~9)...`, where `~` marks an estimate) and the summary is printed to stdout
as Markdown. `--language` accepts the allowlisted codes (default:
`VIDBRIEF_DEFAULT_SUMMARY_LANGUAGE`) and `--verbose` shows JSON logs at
`VIDBRIEF_LOG_LEVEL`. The exit status is 0 on success, 1 when the video cannot be
summarized, 2 for invalid arguments or configuration and 130 when cancelled with Ctrl+C.

## Configuration

All settings are read from environment variables or `.env`. See [`.env.example`](.env.example).

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — (required) | Groq API key |
| `VIDBRIEF_TRANSCRIPTION_MODEL` | `whisper-large-v3-turbo` | Speech-to-text model |
| `VIDBRIEF_SUMMARY_MODEL` | `openai/gpt-oss-120b` | LLM used for summaries |
| `VIDBRIEF_DEFAULT_SUMMARY_LANGUAGE` | `pt-BR` | Default summary language (allowlisted) |
| `VIDBRIEF_MAX_VIDEO_DURATION_SECONDS` | `7200` | Longest video accepted |
| `VIDBRIEF_AUDIO_CHUNK_MAX_MB` | `24` | Max audio chunk size sent to Groq, in decimal MB |
| `VIDBRIEF_SUMMARY_MAX_REQUEST_TOKENS` | — (automatic) | Fixed token budget (prompt + answer) per summary request, 2000 to 131072; unset follows the limit Groq reports |
| `VIDBRIEF_REQUEST_TIMEOUT_SECONDS` | `120` | Timeout for external API calls |
| `VIDBRIEF_MAX_CONCURRENT_JOBS` | `1` | Parallel summarization jobs |
| `VIDBRIEF_HOST` | `127.0.0.1` | Bind address (loopback only) |
| `VIDBRIEF_PORT` | `8000` | HTTP port |
| `VIDBRIEF_LOG_LEVEL` | `INFO` | Log verbosity |

## Development

Tasks are defined in `pyproject.toml` and run the same way on every system:

```bash
uv run poe            # list all tasks
uv run poe format     # auto-format and fix lint issues
uv run poe check      # lint + typecheck + tests + dependency audit
```

CI runs every pre-commit hook and the dependency audit, then the type checks and tests
(including the real-ffmpeg ones) on Ubuntu, macOS and Windows. Actions are pinned to
commit SHAs and Dependabot proposes weekly updates for them and for `uv.lock`.

Integration tests hit real services and are skipped by default: `uv run pytest -m integration`.
The Groq tests need `GROQ_API_KEY` in `.env`; they use about 20 seconds of the audio
quota and a few hundred chat tokens.

## Security

- Runs locally only: the server refuses to bind to non-loopback addresses.
- Secrets are loaded from `.env` (git-ignored) and never logged: logs are structured JSON
  on stderr, and Groq API keys are masked as `[REDACTED]` in messages, extra fields
  (including values nested in objects) and tracebacks.
- Only YouTube URLs are accepted (SSRF protection): links with credentials, custom ports, IP
  addresses or non-HTTP schemes are rejected, and downstream tools only ever receive a
  canonical URL rebuilt from the validated video ID.
- ffmpeg runs without a shell and may only open local files (`-protocol_whitelist file`), so
  a crafted media file cannot make it fetch URLs.
- Errors from Groq are reduced to fixed reason codes, so provider messages never reach the
  UI or the logs, and transcript text is never logged.
- Transcripts are treated as untrusted data in LLM prompts (prompt-injection mitigation):
  they are sent between delimiter tags (forged tags are removed) under rules that forbid
  following instructions found in them, the model has no tools, its answer must match a
  strict JSON schema, and the summary language comes only from the allowlist.
- LLM output is sanitized before rendering (XSS protection). In the Markdown report, the
  video title and the summary are flattened to single lines, stripped of control and
  bidirectional characters and escaped, so they cannot inject links, HTML or terminal
  escape sequences.

## Legal notice

Downloading YouTube content may conflict with YouTube's Terms of Service. vidbrief is intended for personal and educational use; you are responsible for how you use it.

## License

[MIT](LICENSE) © mbarboss
