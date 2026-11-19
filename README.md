# YT_Clips_Antigravity

> **Automated YouTube-to-Shorts/Reels Clipping Pipeline powered by Google Gemini & Faster-Whisper for Google Antigravity.**

---

## ⚡ Overview
`YT_Clips_Antigravity` transforms long-form YouTube videos and multi-hour livestreams into ready-to-post, high-retention 9:16 vertical Shorts and Reels:

1. **True 1080p High-Bitrate Output**:
   - `yt-dlp` captures pristine VP9/AV1 1080p/4K streams using `bv*[height<=2160]+ba/b`.
   - FFmpeg encodes at `1080x1920` with `-crf 17`, `-preset slow`, `-pix_fmt yuv420p`, Lanczos scaling (`scale=1080:1920:flags=lanczos`), and unsharp filter (`unsharp=5:5:0.6:5:5:0.0`).
2. **Three 9:16 Layout Modes**:
   - `split` (Streamer Split-Screen): Top 1080x960 scales facecam (`--facecam top-right | top-left | bottom-left | bottom-right`), bottom 1080x960 scales gameplay via `vstack`.
   - `blur` (Blurred Fill): 16:9 stream centered vertically over a zoomed, Gaussian-blurred (`gblur=sigma=30`) 1080x1920 background.
   - `zoom` (Zoomed In): Standard 9:16 center-crop scaled to 1080x1920.
3. **Top-Right Channel Watermark**:
   - Automatically detects streamer channel name via `yt-dlp --print "%(channel)s" --no-download <URL>`.
   - Burns a semi-transparent white watermark with dark shadow into the top-right corner (`x=w-tw-36:y=42`).
4. **Quota Protection & Automatic Gemini Fallback**:
   - Seamlessly cycles through `["gemini-4-hydrogen", "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]`.
   - Automatically catches 429 quota exhaustion and 503 spikes, switching models without crashing.
5. **Interactive Clip Count & Default Saving**:
   - Prompts for clip count, layout mode, and saving preferences into `config.json`.
6. **Unattended Automation (`auto_run.py`)**:
   - Supports 5-hour long continuous batch runs, Google Drive upload, and automatic local cleanup.

---

## 📁 Repository Structure
```plaintext
YT_Clips_Antigravity/
├── .agents/
│   └── skills/
│       └── yt-clip-pipeline/
│           └── SKILL.md            # Antigravity agent skill
├── clipper.py                      # Core 1080p clipping & captioning engine
├── auto_run.py                     # Unattended runner (5-hour batch loops, GDrive upload, cleanup)
├── config.json                     # Persistent defaults for clips, layout, and models
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment template
└── output_clips/
    └── clips_metadata.json         # Generated titles, Gen-Z punchlines, captions & hashtags
```

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python 3.12+**
- **FFmpeg** on system PATH (`ffmpeg -version` with `libass` support).
- **Gemini API Key**: From [Google AI Studio](https://aistudio.google.com/).

### 2. Installation
```bash
git clone https://github.com/OmChauhan07/YT_Clips_Antigravity.git
cd YT_Clips_Antigravity

# Create virtual environment
uv venv .venv
.\.venv\Scripts\activate   # On Windows
# source .venv/bin/activate # On Linux/macOS

# Install dependencies
uv pip install -r requirements.txt
```

### 3. Environment Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Add your key inside `.env`:
```env
GEMINI_API_KEY=your_gemini_api_key_here

# Optional: Google Drive upload folder ID
GDRIVE_FOLDER_ID=your_gdrive_folder_id_here
```

---

## 💻 Usage

### Interactive CLI Run
```bash
python clipper.py "https://www.youtube.com/watch?v=VIDEO_ID" --clips 3 --layout split --facecam top-right --save-config
```

#### Layout Options:
- `--layout split`: Facecam on top, gameplay on bottom.
- `--layout blur`: Full 16:9 stream with blurred background.
- `--layout zoom`: Standard 9:16 center crop.

### Unattended 5-Hour Batch Automation
```bash
# Run continuous monitoring / batch processing for 5 hours with local cleanup
python auto_run.py "https://www.youtube.com/watch?v=VIDEO_ID" --duration-hours 5.0 --interval 300 --local-cleanup
```

### Google Antigravity Natural Language Trigger
In the Antigravity chat, paste:
> *"Clip this YouTube video: https://www.youtube.com/watch?v=VIDEO_ID"*

Antigravity will automatically prompt you for:
1. Desired clip count (`1` for quick test, `3` default)
2. Desired layout (`split`, `blur`, `zoom`)
3. Saving as default in `config.json`

---

## 📄 License
MIT License.
