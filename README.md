# vidbrief

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
| Quality | Ruff, mypy (strict), pytest, pre-commit |
| Security | Ruff security rules (Bandit), detect-secrets, pip-audit |

## Prerequisites

- Ubuntu (or another Linux distribution)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Deno](https://deno.com/) (required by yt-dlp for YouTube)
- ffmpeg
- A [Groq API key](https://console.groq.com/keys)

## Getting started

```bash
git clone https://github.com/mbarboss/vidbrief.git
cd vidbrief
make install
cp .env.example .env && chmod 600 .env
# Edit .env and set GROQ_API_KEY
```

## Configuration

All settings are read from environment variables or `.env`. See [`.env.example`](.env.example).

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — (required) | Groq API key |
| `VIDBRIEF_TRANSCRIPTION_MODEL` | `whisper-large-v3-turbo` | Speech-to-text model |
| `VIDBRIEF_SUMMARY_MODEL` | `openai/gpt-oss-120b` | LLM used for summaries |
| `VIDBRIEF_DEFAULT_SUMMARY_LANGUAGE` | `pt-BR` | Default summary language (allowlisted) |
| `VIDBRIEF_MAX_VIDEO_DURATION_SECONDS` | `7200` | Longest video accepted |
| `VIDBRIEF_AUDIO_CHUNK_MAX_MB` | `24` | Max audio chunk size sent to Groq |
| `VIDBRIEF_REQUEST_TIMEOUT_SECONDS` | `120` | Timeout for external API calls |
| `VIDBRIEF_MAX_CONCURRENT_JOBS` | `1` | Parallel summarization jobs |
| `VIDBRIEF_HOST` | `127.0.0.1` | Bind address (loopback only) |
| `VIDBRIEF_PORT` | `8000` | HTTP port |
| `VIDBRIEF_LOG_LEVEL` | `INFO` | Log verbosity |

## Development

```bash
make help       # list all targets
make format     # auto-format and fix lint issues
make check      # lint + typecheck + tests + dependency audit
```

Integration tests hit real services and are skipped by default: `uv run pytest -m integration`.

## Security

- Runs locally only: the server refuses to bind to non-loopback addresses.
- Secrets are loaded from `.env` (git-ignored) and never logged: logs are structured JSON
  on stderr, and Groq API keys are masked as `[REDACTED]` in messages, extra fields and
  tracebacks.
- Only YouTube URLs are accepted (SSRF protection): links with credentials, custom ports, IP
  addresses or non-HTTP schemes are rejected, and downstream tools only ever receive a
  canonical URL rebuilt from the validated video ID.
- Transcripts are treated as untrusted data in LLM prompts (prompt-injection mitigation).
- LLM output is sanitized before rendering (XSS protection).

## Legal notice

Downloading YouTube content may conflict with YouTube's Terms of Service. vidbrief is intended for personal and educational use; you are responsible for how you use it.

## License

[MIT](LICENSE) © mbarboss
