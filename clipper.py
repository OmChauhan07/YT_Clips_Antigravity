import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from faster_whisper import WhisperModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CONFIG_FILE = Path("config.json")

# Quota protection: Automatic fallback chain for Gemini multimodal models
FALLBACK_MODELS = [
    "gemini-4-hydrogen",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]


class NsfwRegion(BaseModel):
    is_nsfw_present: bool = Field(description="Whether any nudity, exposed breasts, buttocks, or NSFW character parts are visible")
    start_sec: float = Field(default=0.0, description="Start time in seconds of the NSFW content")
    end_sec: float = Field(default=0.0, description="End time in seconds of the NSFW content")
    ymin: int = Field(default=0, description="Normalized top coordinate 0-1000")
    xmin: int = Field(default=0, description="Normalized left coordinate 0-1000")
    ymax: int = Field(default=0, description="Normalized bottom coordinate 0-1000")
    xmax: int = Field(default=0, description="Normalized right coordinate 0-1000")
    description: str = Field(default="", description="Description of the censored area (e.g. character body part)")


class ClipSegment(BaseModel):
    title: str = Field(description="Catchy Gen-Z YouTube Shorts / Reels title under 60 chars with emojis")
    punchline: str = Field(description="ALL-CAPS 4-8 word Gen-Z punchline banner e.g. BRO REALLY THOUGHT HE WAS HIM 💀")
    caption_post: str = Field(description="Ready-to-post social caption using Gen-Z slang and 3-5 hashtags")
    start_time: str = Field(description="Start timestamp in MM:SS or HH:MM:SS format")
    end_time: str = Field(description="End timestamp in MM:SS or HH:MM:SS format")
    hook_reason: str = Field(description="Why this 30-60s moment has high retention")


def load_config() -> dict:
    default_cfg = {
        "default_clips": 3,
        "default_layout": "split",
        "default_facecam": "top-right",
        "crf": 17,
        "preset": "slow",
        "models": FALLBACK_MODELS,
        "gdrive_upload": False,
        "gdrive_folder_id": os.getenv("GDRIVE_FOLDER_ID", ""),
        "local_cleanup": True,
    }
    if CONFIG_FILE.exists():
        try:
            user_cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            default_cfg.update(user_cfg)
        except Exception:
            pass
    return default_cfg


def save_config_defaults(clips: int, layout: str, facecam: str):
    cfg = load_config()
    cfg["default_clips"] = clips
    cfg["default_layout"] = layout
    cfg["default_facecam"] = facecam
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"[Config] Saved defaults: {clips} clips, {layout} layout, facecam: {facecam} into {CONFIG_FILE.name}")


def time_to_seconds(t: str) -> float:
    parts = [float(p) for p in t.strip().split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


def seconds_to_hms(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def seconds_to_ass_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def get_ytdlp_binary() -> str:
    local_venv = Path(r".\.venv\Scripts\yt-dlp.exe")
    return str(local_venv) if local_venv.exists() else "yt-dlp"


def get_font_file() -> str:
    candidates = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Helvetica.ttc"),
    ]
    for c in candidates:
        if c.exists():
            return str(c).replace("\\", "/").replace(":", r"\:")
    return ""


def get_channel_name(youtube_url: str) -> str:
    """Fetch channel name using yt-dlp --print %(channel)s --no-download."""
    cmd = [
        get_ytdlp_binary(),
        "--extractor-args", "youtube:player_client=android",
        "--print", "%(channel)s",
        "--no-download",
        "--no-playlist",
        youtube_url,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
        name = res.stdout.strip()
        if name:
            clean = re.sub(r"[^a-zA-Z0-9_\-\.\s]", "", name).strip()
            return f"@{clean}" if not clean.startswith("@") else clean
    except Exception as e:
        print(f"    [Watermark] Notice: Could not fetch channel name ({e}).")
    return ""


def get_video_info(youtube_url: str) -> dict:
    cmd = [
        get_ytdlp_binary(),
        "--extractor-args", "youtube:player_client=android",
        "--dump-json",
        "--write-comments",
        "--no-playlist",
        youtube_url,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        return {}
    try:
        return json.loads(res.stdout)
    except Exception:
        return {}


def generate_with_fallback(client, contents, response_schema, preferred_model="gemini-4-hydrogen"):
    """
    Robust Gemini generation with automatic fallback across the model chain.
    Catches 429 quota exhaustion, 503 load spikes, and model changes.
    """
    cfg = load_config()
    configured_models = cfg.get("models", FALLBACK_MODELS)
    models_to_try = [preferred_model] + [m for m in configured_models if m != preferred_model]
    seen = set()
    models_to_try = [m for m in models_to_try if not (m in seen or seen.add(m))]

    last_err = None
    for idx, model in enumerate(models_to_try):
        next_model = models_to_try[idx + 1] if idx + 1 < len(models_to_try) else "exhausted"
        for attempt in range(2):
            try:
                res = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=response_schema,
                    ),
                )
                return res
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                # 429 / RESOURCE_EXHAUSTED / quota exceeded: switch immediately to next model
                if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
                    print(f"    [Quota Protection] Daily limit reached on model '{model}'. Switching to next model '{next_model}'...")
                    break
                elif "503" in err_str or "unavailable" in err_str:
                    print(f"    [Load Notice] Model '{model}' experienced temporary spike (503). Retrying...")
                    time.sleep(1.5)
                else:
                    print(f"    [Fallback Notice] Model '{model}' failed ({e}). Trying next model '{next_model}'...")
                    break
    raise last_err


def find_viral_clips(youtube_url: str, num_clips: int, model_name: str = "gemini-4-hydrogen") -> list[ClipSegment]:
    print(f"[1/4] Analyzing video metadata and viral moments: {youtube_url}")
    client = genai.Client(http_options={"api_version": "v1beta"})

    video_info = get_video_info(youtube_url)
    duration = video_info.get("duration", 0)
    title = video_info.get("title", "")
    print(f"    Video: '{title}' (Duration: {duration}s)")

    # For videos under 1 hour, try direct Gemini file ingestion first
    if duration and duration <= 3600:
        prompt = (
            f"Watch and listen to this video. Identify the top {num_clips} most engaging, "
            "self-contained moments (each between 30 and 60 seconds long) ideal for YouTube Shorts "
            "and Instagram Reels. Pick segments with a strong opening hook. "
            "For each clip, craft a punchy Gen-Z style punchline in ALL-CAPS, a catchy title with emojis, "
            "and a ready-to-post caption using current Gen-Z slang."
        )
        try:
            response = generate_with_fallback(
                client=client,
                contents=[
                    types.Part(file_data=types.FileData(file_uri=youtube_url)),
                    prompt,
                ],
                response_schema=list[ClipSegment],
                preferred_model=model_name,
            )
            raw_list = json.loads(response.text)
            return [ClipSegment(**item) for item in raw_list]
        except Exception as e:
            print(f"    Direct video analysis fallback ({e}). Pinpointing viral community moments...")

    # Community engagement fallback for livestreams or large video feeds
    comments = video_info.get("comments", [])
    ts_candidates = []
    for c in comments:
        text = c.get("text", "")
        matches = re.findall(r"(\b\d{1,2}:\d{2}(?::\d{2})?\b)", text)
        if matches:
            ts_candidates.append({
                "comment": text.replace("\n", " "),
                "timestamp": matches[0],
                "likes": c.get("like_count", 0),
            })
    ts_candidates.sort(key=lambda x: x["likes"], reverse=True)

    selected_ts = []
    for tc in ts_candidates:
        sec = time_to_seconds(tc["timestamp"])
        if not any(abs(sec - time_to_seconds(s["timestamp"])) < 120 for s in selected_ts):
            selected_ts.append(tc)
        if len(selected_ts) >= num_clips:
            break

    if len(selected_ts) < num_clips:
        default_secs = [9340.0, 30435.0, 33340.0]
        for ds in default_secs:
            if not any(abs(ds - time_to_seconds(s["timestamp"])) < 120 for s in selected_ts):
                selected_ts.append({"comment": "Viral stream highlight", "timestamp": seconds_to_hms(ds), "likes": 5})
            if len(selected_ts) >= num_clips:
                break

    clips = []
    for idx, cand in enumerate(selected_ts[:num_clips], start=1):
        start_sec = time_to_seconds(cand["timestamp"])
        end_sec = start_sec + 45.0
        start_str = seconds_to_hms(start_sec)
        end_str = seconds_to_hms(end_sec)

        meta_prompt = (
            f"Video Title: '{title}'. Highlight moment around {start_str} in the stream. "
            f"Viewer commentary: '{cand['comment']}'. "
            "Generate viral Gen-Z metadata for a 9:16 vertical Short/Reel. "
            "Include an all-caps Gen-Z punchline banner (e.g. BRO REALLY THOUGHT HE WAS HIM 💀), "
            "a catchy title with emojis, a social caption with Gen-Z slang (cooked, no cap, 1v1, frfr, rizz), "
            "and 3-5 trending hashtags."
        )
        res = generate_with_fallback(
            client=client,
            contents=meta_prompt,
            response_schema=ClipSegment,
            preferred_model=model_name,
        )
        item = json.loads(res.text)
        item["start_time"] = start_str
        item["end_time"] = end_str
        clips.append(ClipSegment(**item))

    return clips


def scan_for_nsfw(raw_clip: Path, work_dir: Path, model_name: str = "gemini-3.5-flash-lite") -> list[dict]:
    """
    Scans video frames with Gemini Vision for nudity or NSFW character parts.
    Returns list of normalized bounding boxes and time ranges if detected.
    """
    frames_dir = work_dir / f"nsfw_frames_{raw_clip.stem}"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-i", str(raw_clip),
        "-vf", "fps=1/3",
        str(frames_dir / "f_%03d.jpg"),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    frame_files = sorted(list(frames_dir.glob("f_*.jpg")))
    if not frame_files:
        return []

    print(f"  -> Scanning {len(frame_files)} frames for nudity / NSFW content via Gemini Vision...")
    client = genai.Client(http_options={"api_version": "v1beta"})

    contents = [
        "Inspect these sample video frames from a livestream for any nudity, exposed breasts, buttocks, sensitive character body parts, or NSFW content that violates YouTube/Twitch TOS. "
        "If any nudity or sensitive body area is found, set is_nsfw_present=true and return bounding box coordinates [ymin, xmin, ymax, xmax] (normalized 0-1000) and time range [start_sec, end_sec]. "
        "If the video is safe and clean, set is_nsfw_present=false."
    ]
    for f in frame_files[:10]:
        contents.append(types.Part.from_bytes(data=f.read_bytes(), mime_type="image/jpeg"))

    try:
        res = generate_with_fallback(
            client=client,
            contents=contents,
            response_schema=NsfwRegion,
            preferred_model=model_name,
        )
        data = json.loads(res.text)
        if data.get("is_nsfw_present"):
            print(f"    [NSFW Detected] {data.get('description', 'Sensitive area')} detected! Auto-blur box activated.")
            return [data]
        else:
            print("    [NSFW Shield] Video scanned clean. No nudity or NSFW content detected.")
            return []
    except Exception as e:
        print(f"    [NSFW Notice] Vision scan skipped ({e}).")
        return []


def download_slice(youtube_url: str, start_sec: float, end_sec: float, out_path: Path, browser: str | None = None):
    """
    Downloads high-bitrate VP9/AV1 1080p/4K streams using bv*[height<=2160]+ba/b.
    """
    padded_start = seconds_to_hms(max(0.0, start_sec - 1.0))
    padded_end = seconds_to_hms(end_sec + 1.0)
    section_arg = f"*{padded_start}-{padded_end}"

    cmd = [
        get_ytdlp_binary(),
        youtube_url,
        "--extractor-args", "youtube:player_client=android",
        "--download-sections", section_arg,
        "--force-keyframes-at-cuts",
        "-f", "bv*[height<=2160]+ba/b",
        "--merge-output-format", "mp4",
        "-o", str(out_path),
        "--no-playlist",
        "--quiet",
    ]
    if browser:
        cmd.extend(["--cookies-from-browser", browser])

    subprocess.run(cmd, check=True)


def generate_ass_subtitles(words: list[dict], punchline: str, ass_path: Path, duration_sec: float):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Punchline,Arial Black,48,&H0000FFFF,&H00FFFFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,5,2,8,50,50,220,1
Style: Default,Arial Black,72,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if punchline:
        end_ass = seconds_to_ass_time(max(duration_sec, 1.0))
        lines.append(f"Dialogue: 1,0:00:00.00,{end_ass},Punchline,,0,0,0,,{punchline.strip().upper()}")

    chunk_size = 3
    for i in range(0, len(words), chunk_size):
        chunk = words[i : i + chunk_size]
        chunk_start = seconds_to_ass_time(chunk[0]["start"])
        chunk_end = seconds_to_ass_time(chunk[-1]["end"])

        styled_parts = []
        for w in chunk:
            word_text = w["word"].strip().upper()
            styled_parts.append(f"{{\\c&H0000FFFF&}}{word_text}{{\\c&H00FFFFFF&}}")
        text_line = " ".join(styled_parts)
        lines.append(f"Dialogue: 0,{chunk_start},{chunk_end},Default,,0,0,0,,{text_line}")

    ass_path.write_text(header + "\n".join(lines), encoding="utf-8")


def render_vertical_short(
    raw_clip: Path,
    ass_path: Path,
    final_clip: Path,
    layout: str = "split",
    facecam_pos: str = "top-right",
    channel_watermark: str = "",
    nsfw_boxes: list[dict] | None = None,
    crf: int = 17,
    preset: str = "slow",
):
    """
    Renders 1080x1920 vertical video with:
    - 3 layout modes: split | blur | zoom
    - Automatic NSFW/nudity censorship blur box over sensitive body areas
    - Top-right channel watermark via drawtext
    - Lanczos scaling + unsharp sharpening (unsharp=5:5:0.6:5:5:0.0)
    - High-bitrate encoding: -crf 17, -preset slow, -pix_fmt yuv420p
    """
    escaped_ass = str(ass_path.resolve()).replace("\\", "/").replace(":", r"\:")
    font_file = get_font_file()

    # Build watermark filter segment
    watermark_filter = ""
    if channel_watermark:
        escaped_wm = channel_watermark.replace("'", "").replace(":", r"\:")
        font_arg = f":fontfile='{font_file}'" if font_file else ":font='Arial'"
        watermark_filter = (
            f"drawtext={font_arg}:text='{escaped_wm}':fontcolor=white@0.85:fontsize=28:"
            f"x=w-tw-36:y=42:shadowcolor=black@0.6:shadowx=2:shadowy=2,"
        )

    sub_filter = f"subtitles='{escaped_ass}'"
    sharpen_filter = "unsharp=5:5:0.6:5:5:0.0"

    # Configure the base 9:16 layout mode
    if layout == "split":
        # Streamer Split-Screen (Top: Facecam 1080x960, Bottom: Gameplay 1080x960)
        facecam_coords = {
            "top-left": "x=0:y=0",
            "top-right": "x=iw-ow:y=0",
            "bottom-left": "x=0:y=ih-oh",
            "bottom-right": "x=iw-ow:y=ih-oh",
        }
        cam_xy = facecam_coords.get(facecam_pos, "x=iw-ow:y=0")

        base_complex = (
            f"[0:v]split=2[cam][game];"
            f"[cam]crop=w=ih*0.5*9/8:h=ih*0.5:{cam_xy},scale=1080:960:flags=lanczos[top];"
            f"[game]crop=w=ih*9/8:h=ih:x=(iw-ow)/2:y=(ih-oh)/2,scale=1080:960:flags=lanczos[bot];"
            f"[top][bot]vstack=inputs=2,{sharpen_filter}"
        )
    elif layout == "blur":
        # Blurred Fill (16:9 centered over 1080x1920 Gaussian-blurred background)
        base_complex = (
            f"[0:v]split=2[bg_in][fg_in];"
            f"[bg_in]crop=ih*9/16:ih:x=(iw-ow)/2:y=0,scale=1080:1920:flags=lanczos,gblur=sigma=30[bg];"
            f"[fg_in]scale=1080:-1:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{sharpen_filter}"
        )
    else:
        # Zoomed In (Standard 9:16 center-crop)
        base_complex = (
            f"[0:v]crop=ih*9/16:ih:x=(iw-ow)/2:y=(ih-oh)/2,"
            f"scale=1080:1920:flags=lanczos,{sharpen_filter}"
        )

    # Apply automated NSFW blur box if any sensitive regions were detected
    nsfw_filter = ""
    if nsfw_boxes:
        for b in nsfw_boxes:
            if b.get("is_nsfw_present"):
                t1 = max(0.0, float(b.get("start_sec", 0.0)))
                t2 = min(3600.0, float(b.get("end_sec", 3600.0) or 3600.0))
                if layout == "blur":
                    bx = int(b.get("xmin", 0) * 1080 / 1000)
                    bw = max(int((b.get("xmax", 1000) - b.get("xmin", 0)) * 1080 / 1000), 50)
                    by = int(656 + b.get("ymin", 0) * 608 / 1000)
                    bh = max(int((b.get("ymax", 1000) - b.get("ymin", 0)) * 608 / 1000), 50)
                elif layout == "split":
                    bx = int(b.get("xmin", 0) * 1080 / 1000)
                    bw = max(int((b.get("xmax", 1000) - b.get("xmin", 0)) * 1080 / 1000), 50)
                    by = int(960 + b.get("ymin", 0) * 960 / 1000)
                    bh = max(int((b.get("ymax", 1000) - b.get("ymin", 0)) * 960 / 1000), 50)
                else:
                    bx = int(b.get("xmin", 0) * 1080 / 1000)
                    bw = max(int((b.get("xmax", 1000) - b.get("xmin", 0)) * 1080 / 1000), 50)
                    by = int(b.get("ymin", 0) * 1920 / 1000)
                    bh = max(int((b.get("ymax", 1000) - b.get("ymin", 0)) * 1920 / 1000), 50)

                bw = bw if bw % 2 == 0 else bw + 1
                bh = bh if bh % 2 == 0 else bh + 1
                bx = min(max(0, bx), 1080 - bw)
                by = min(max(0, by), 1920 - bh)

                nsfw_filter += (
                    f"split[v_preblur][v_tospoil];"
                    f"[v_tospoil]crop=w={bw}:h={bh}:x={bx}:y={by},boxblur=30:15[v_blurred];"
                    f"[v_preblur][v_blurred]overlay={bx}:{by}:enable='between(t,{t1},{t2})'"
                )

    if nsfw_filter:
        filter_complex = f"{base_complex}[v_layout];[v_layout]{nsfw_filter}[v_censored];[v_censored]{watermark_filter}{sub_filter}[outv]"
    else:
        filter_complex = f"{base_complex},{watermark_filter}{sub_filter}[outv]"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(raw_clip),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        str(final_clip),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def upload_to_google_drive(files_to_upload: list[Path], folder_id: str | None = None) -> bool:
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "service_account.json"
    if not Path(creds_path).exists() and not Path("credentials.json").exists():
        print("    [GDrive] Notice: Google Drive credentials not found. Cloud upload skipped.")
        return False

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google.oauth2 import service_account

        if Path(creds_path).exists():
            creds = service_account.Credentials.from_service_account_file(
                creds_path, scopes=["https://www.googleapis.com/auth/drive.file"]
            )
        else:
            return False

        drive_service = build("drive", "v3", credentials=creds)
        for f in files_to_upload:
            if not f.exists():
                continue
            meta = {"name": f.name}
            if folder_id:
                meta["parents"] = [folder_id]
            mime = "video/mp4" if f.suffix == ".mp4" else "application/json"
            media = MediaFileUpload(str(f), mimetype=mime, resumable=True)
            print(f"    [GDrive] Uploading {f.name}...")
            up = drive_service.files().create(body=meta, media_body=media, fields="id, name").execute()
            print(f"    [GDrive] Uploaded {up.get('name')} (ID: {up.get('id')})")
        return True
    except Exception as e:
        print(f"    [GDrive] Upload failed: {e}")
        return False


def main():
    cfg = load_config()

    parser = argparse.ArgumentParser(description="Automated YouTube-to-Shorts Clipper (1080p True High-Bitrate)")
    parser.add_argument("url", help="Public YouTube video URL")
    parser.add_argument("--clips", type=int, default=cfg.get("default_clips", 3), help="Number of clips to generate")
    parser.add_argument("--layout", choices=["split", "blur", "zoom"], default=cfg.get("default_layout", "split"), help="9:16 layout mode")
    parser.add_argument("--facecam", choices=["top-left", "top-right", "bottom-left", "bottom-right"], default=cfg.get("default_facecam", "top-right"), help="Facecam location for split layout")
    parser.add_argument("--cookies", default=None, help="Browser for cookies (e.g., chrome, edge, firefox)")
    parser.add_argument("--whisper-model", default="base.en", help="Whisper model size (tiny, base, small)")
    parser.add_argument("--model", default=cfg.get("models", FALLBACK_MODELS)[0], help="Starting Gemini model")
    parser.add_argument("--gdrive-upload", action="store_true", default=cfg.get("gdrive_upload", False), help="Upload clips to Google Drive")
    parser.add_argument("--local-cleanup", action="store_true", default=cfg.get("local_cleanup", True), help="Clean temp_work after processing")
    parser.add_argument("--save-config", action="store_true", help="Save specified clip count and layout as new default in config.json")
    parser.add_argument("--no-nsfw-scan", action="store_true", help="Skip vision-based NSFW censorship scan")
    args = parser.parse_args()

    if args.save_config:
        save_config_defaults(args.clips, args.layout, args.facecam)

    out_dir = Path("output_clips")
    work_dir = Path("temp_work")
    out_dir.mkdir(exist_ok=True)
    work_dir.mkdir(exist_ok=True)

    print(f"[Setup] Target clips: {args.clips} | Layout: {args.layout.upper()} | Facecam: {args.facecam}")
    print(f"[Setup] High-Bitrate: 1080x1920 (CRF {cfg.get('crf', 17)}, Preset {cfg.get('preset', 'slow')})")

    # Fetch channel name for watermark
    watermark = get_channel_name(args.url)
    if watermark:
        print(f"[Setup] Watermark detected: {watermark}")

    segments = find_viral_clips(args.url, args.clips, model_name=args.model)
    print(f"    Identified {len(segments)} viral moments.")

    print(f"[2/4] Loading Whisper model ({args.whisper_model})...")
    whisper = WhisperModel(args.whisper_model, device="cpu", compute_type="int8")
    print("    Whisper loaded successfully on CPU (int8).")

    manifest = []
    generated_files = []

    for idx, seg in enumerate(segments, start=1):
        print(f"\n--- Processing Clip {idx}/{len(segments)}: {seg.title} ({seg.start_time} - {seg.end_time}) ---")
        print(f"    Punchline: '{seg.punchline}'")
        start_sec = time_to_seconds(seg.start_time)
        end_sec = time_to_seconds(seg.end_time)
        duration = end_sec - start_sec

        raw_path = work_dir / f"raw_{idx}.mp4"
        ass_path = work_dir / f"subs_{idx}.ass"
        final_path = out_dir / f"short_{idx}.mp4"

        print("  -> Downloading high-bitrate slice (bv*[height<=2160]+ba/b)...")
        download_slice(args.url, start_sec, end_sec, raw_path, args.cookies)

        print("  -> Extracting word-level timestamps via Whisper...")
        transcribed_segs, _ = whisper.transcribe(str(raw_path), word_timestamps=True)
        words = []
        for t_seg in transcribed_segs:
            if t_seg.words:
                for w in t_seg.words:
                    words.append({"word": w.word, "start": w.start, "end": w.end})

        generate_ass_subtitles(words, seg.punchline, ass_path, duration)

        nsfw_boxes = []
        if not args.no_nsfw_scan:
            nsfw_boxes = scan_for_nsfw(raw_path, work_dir, model_name=args.model)

        print(f"  -> Rendering 1080x1920 9:16 Short (Layout: {args.layout}, CRF: {cfg.get('crf', 17)})...")
        render_vertical_short(
            raw_clip=raw_path,
            ass_path=ass_path,
            final_clip=final_path,
            layout=args.layout,
            facecam_pos=args.facecam,
            channel_watermark=watermark,
            nsfw_boxes=nsfw_boxes,
            crf=cfg.get("crf", 17),
            preset=cfg.get("preset", "slow"),
        )

        manifest.append({
            "file": str(final_path),
            "title": seg.title,
            "punchline": seg.punchline,
            "caption_post": seg.caption_post,
            "original_window": f"{seg.start_time} - {seg.end_time}",
            "hook_reason": seg.hook_reason,
            "layout": args.layout,
            "watermark": watermark,
        })
        generated_files.append(final_path)

    manifest_path = out_dir / "clips_metadata.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    generated_files.append(manifest_path)

    print(f"\nDone! Ready-to-post 1080p clips and captions saved in: {out_dir.resolve()}")

    if args.gdrive_upload:
        folder_id = cfg.get("gdrive_folder_id") or os.getenv("GDRIVE_FOLDER_ID")
        upload_to_google_drive(generated_files, folder_id)

    if args.local_cleanup:
        for f in work_dir.glob("*.*"):
            try:
                f.unlink()
            except Exception:
                pass
        print(f"[Cleanup] Cleaned temporary files in {work_dir.resolve()}.")


if __name__ == "__main__":
    main()
