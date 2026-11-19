# YT_Clips_Antigravity

> **Automated YouTube-to-Shorts/Reels Clipping Pipeline powered by Google Gemini & Faster-Whisper for Google Antigravity.**

---

## ⚡ Overview
`YT_Clips_Antigravity` automatically transforms long-form YouTube videos and multi-hour livestreams into ready-to-post, high-retention 9:16 vertical Shorts and Reels:
- **Intelligent Highlight Detection**: Uses Google Gemini to detect viral moments and community engagement peaks without downloading the entire video.
- **Precision Slicing**: Slices only the exact target segments via `yt-dlp` using keyframe-accurate cuts.
- **Word-Level Subtitles**: Transcribes audio word-by-word with `faster-whisper`.
- **Trendy Gen-Z Styling**: Burns in high-contrast ALL-CAPS Gen-Z punchline banners at the top and synchronized yellow-highlighted karaoke captions in the lower-third.
- **Free-Tier Model Resilience**: Automatically cycles through free-tier Gemini models (`gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-2.5-flash`, etc.) when daily quotas or rate limits are reached.
- **Antigravity Skill Integration**: Includes a pre-configured workspace skill (`.agents/skills/yt-clip-pipeline/SKILL.md`) for seamless natural language execution in Antigravity chat.

---

## 📁 Repository Structure
```plaintext
YT_Clips_Antigravity/
├── .agents/
│   └── skills/
│       └── yt-clip-pipeline/
│           └── SKILL.md            # Antigravity agent skill
├── clipper.py                      # Complete end-to-end Python pipeline
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment template
└── output_clips/
    └── clips_metadata.json         # Example generated metadata (titles, captions, hashtags)
```

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python 3.12+**
- **FFmpeg** installed and on system PATH (with `libass` support).
  - Verify with: `ffmpeg -version`
- **Gemini API Key**: Obtain a free key from [Google AI Studio](https://aistudio.google.com/).

### 2. Installation
Clone the repository and set up a virtual environment:
```bash
git clone https://github.com/OmChauhan07/YT_Clips_Antigravity.git
cd YT_Clips_Antigravity

# Create virtual environment using uv or python
uv venv .venv
.\.venv\Scripts\activate   # On Windows
# source .venv/bin/activate # On Linux/macOS

# Install dependencies
uv pip install -r requirements.txt
# or: pip install -r requirements.txt
```

### 3. Environment Configuration
Copy the template and add your Gemini API key:
```bash
cp .env.example .env
```
Inside `.env`:
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## 💻 Usage

### Command Line
Run `clipper.py` with your YouTube video or livestream link:
```bash
python clipper.py "https://www.youtube.com/watch?v=YOUR_VIDEO_ID" --clips 3
```

#### Optional Flags:
- `--clips <int>`: Number of viral clips to extract (default: `3`).
- `--model <str>`: Specific Gemini model to start with (default: `gemini-3.8-flash`).
- `--whisper-model <str>`: Whisper model size (`tiny`, `base.en`, `small`, etc. default: `base.en`).
- `--cookies <browser>`: Browser name (`chrome`, `edge`, `firefox`) if cookies are needed.

### Using Google Antigravity
Simply type in the Antigravity chat:
> *"Clip this video: https://www.youtube.com/watch?v=YOUR_VIDEO_ID"*

---

## 📦 Output
All generated assets are exported to `output_clips/`:
- `short_1.mp4`, `short_2.mp4`, `short_3.mp4`: 1080x1920 vertical video clips.
- `clips_metadata.json`: Ready-to-copy titles with emojis, Gen-Z punchlines, post captions with hashtags, and retention hook reasons.

---

## 📄 License
MIT License.
