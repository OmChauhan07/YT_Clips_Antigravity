---
name: yt-clip-pipeline
description: Automated YouTube-to-Shorts clipping pipeline. Uses Gemini to detect viral timestamps directly from a public YouTube URL, downloads only those segments with yt-dlp (true 1080p VP9/AV1), transcribes word-level timestamps with faster-whisper, and renders 9:16 vertical clips (split, blur, or zoom layouts) with burned-in dynamic captions, Gen-Z punchline banners, and channel watermarks via FFmpeg.
---

# YouTube Automated Clipping Pipeline

Use this skill whenever the user provides a YouTube link to generate vertical Shorts/Reels or wants to modify/debug the clipping workflow.

## Interactive User Prompts (MANDATORY)
Whenever the user pastes a YouTube link in chat to generate clips, you **MUST ALWAYS ASK** before running `clipper.py`:
1. **Clip Count**: How many clips to generate for this run (e.g., `1` for a quick test, or `3` default).
2. **Layout Mode**: Which 9:16 layout to use:
   - `split`: Streamer split-screen (facecam top 1080x960, gameplay bottom 1080x960). Specify facecam corner if needed (`top-right`, `top-left`, `bottom-left`, `bottom-right`).
   - `blur`: Full 16:9 stream centered over a zoomed, Gaussian-blurred (sigma=30) 1080x1920 background.
   - `zoom`: Standard 9:16 center-crop scaled to 1080x1920.
3. **Save as Default**: Whether to save this clip count and layout as the new default in `config.json` (which `auto_run.py` will also read for unattended runs).

## Prerequisites Check
Before running `clipper.py` or `auto_run.py`, verify in the terminal:
1. `GEMINI_API_KEY` is set in the environment or `.env` file.
2. `ffmpeg` is installed and accessible on PATH (`ffmpeg -version`).
3. Python dependencies from `requirements.txt` are installed (`uv pip install -r requirements.txt`).

## Execution Workflow
1. Run `clipper.py`:
   ```bash
   python clipper.py "<YOUTUBE_URL>" --clips <COUNT> --layout <split|blur|zoom> [--facecam <top-right|top-left|...>] [--save-config]
   ```
2. Unattended runs / Scheduled 5-hour batch loops:
   ```bash
   python auto_run.py "<YOUTUBE_URL>" --duration-hours 5.0 --interval 300
   ```
3. If `yt-dlp` hits a bot check (`Sign in to confirm you're not a bot`), re-run with `--cookies chrome` (or `edge` / `firefox`).
4. Inspect the generated `.mp4` files inside `./output_clips/` along with `clips_metadata.json` (ready-to-paste titles, hooks, Gen-Z punchlines, and hashtags).

## Core Pipeline Specs & Rules
- **True 1080p High-Bitrate**:
  - `yt-dlp` format selection: `bv*[height<=2160]+ba/b` with `--merge-output-format mp4` to capture YouTube's 1080p/4K VP9/AV1 streams.
  - FFmpeg rendering: `scale=1080:1920:flags=lanczos,unsharp=5:5:0.6:5:5:0.0` with `-crf 17`, `-preset slow`, `-pix_fmt yuv420p`, `-c:v libx264`, `-c:a aac -b:a 192k`.
- **Top-Right Channel Watermark**:
  - Automatically fetch streamer's YouTube channel name with `yt-dlp --print "%(channel)s" --no-download <URL>`.
  - Burn watermark into the top-right corner using `drawtext` (`x=w-tw-36:y=42`, fontsize 28, white@0.85 with subtle dark shadow).
- **Gemini Quota Protection & Automatic Fallback**:
  - Antigravity has explicit permission to switch to any available Gemini model whenever a daily API key limit or 429 rate limit is encountered.
  - Active fallback chain: `["gemini-4-hydrogen", "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]`.
  - Automatically catches `429` / `RESOURCE_EXHAUSTED` / `503` / quota limits and immediately retries with the next model without halting.
- **Google Drive & Local Cleanup**:
  - `auto_run.py` and `clipper.py` support `--gdrive-upload` and `--local-cleanup` to purge `temp_work/` and keep disk space clean during long unattended runs.
