---
name: yt-clip-pipeline
description: Automated YouTube-to-Shorts clipping pipeline. Uses Gemini to detect viral timestamps directly from a public YouTube URL, downloads only those segments with yt-dlp, transcribes word-level timestamps with faster-whisper, and renders 9:16 vertical clips with burned-in dynamic captions via FFmpeg.
---

# YouTube Automated Clipping Pipeline

Use this skill whenever the user provides a YouTube link to generate vertical Shorts/Reels or wants to modify/debug the clipping workflow.

## Prerequisites Check
Before running `clipper.py`, verify in the terminal:
1. `GEMINI_API_KEY` is set in the environment or defined in a `.env` file.
2. `ffmpeg` is installed and accessible on PATH (`ffmpeg -version`).
3. Python dependencies from `requirements.txt` are installed (`uv pip install -r requirements.txt` or `pip install -r requirements.txt`).

## Execution Workflow
1. Run `python clipper.py "<YOUTUBE_URL>" --clips 3` (adjust `--clips` if requested).
2. If `yt-dlp` hits a YouTube bot check (`Sign in to confirm you're not a bot`), re-run with `--cookies chrome` (or `edge` / `firefox`) so `yt-dlp` uses local browser cookies.
3. Inspect the generated `.mp4` files inside `./output_clips/` along with `clips_metadata.json` (which contains ready-to-paste titles, hooks, and hashtags for posting).

## Rules for Modifications
- Never download the full video unless the user explicitly provides a private/unlisted link that Gemini cannot access directly. Always keep `--download-sections` active.
- Keep `faster-whisper` compute type on `float16` if CUDA is available, or `int8` on CPU, to stay within 4GB VRAM limits.
- **Free-Tier Model Fallback**: Always utilize free-tier Gemini models (`gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-2.5-flash`, `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.1-flash-lite`). If any model reaches its daily quota or 429 rate limit, automatically cycle to the next available free model without failing or halting the pipeline.
