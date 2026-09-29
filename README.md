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
- Secrets are loaded from `.env` (git-ignored) and never logged.
- Only YouTube URLs are accepted (SSRF protection).
- Transcripts are treated as untrusted data in LLM prompts (prompt-injection mitigation).
- LLM output is sanitized before rendering (XSS protection).

## Legal notice

Downloading YouTube content may conflict with YouTube's Terms of Service. vidbrief is intended for personal and educational use; you are responsible for how you use it.

## License

[MIT](LICENSE) © mbarboss
