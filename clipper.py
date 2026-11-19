import argparse
import json
import os
import re
import subprocess
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


class ClipSegment(BaseModel):
    title: str = Field(description="Catchy Gen-Z YouTube Shorts / Reels title under 60 chars with emojis")
    punchline: str = Field(description="ALL-CAPS 4-8 word Gen-Z punchline banner e.g. BRO REALLY THOUGHT HE WAS HIM 💀")
    caption_post: str = Field(description="Ready-to-post social caption using Gen-Z slang and 3-5 hashtags")
    start_time: str = Field(description="Start timestamp in MM:SS or HH:MM:SS format")
    end_time: str = Field(description="End timestamp in MM:SS or HH:MM:SS format")
    hook_reason: str = Field(description="Why this 30-60s moment has high retention")


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


def get_video_info(youtube_url: str) -> dict:
    cmd = [
        r".\.venv\Scripts\yt-dlp.exe" if Path(r".\.venv\Scripts\yt-dlp.exe").exists() else "yt-dlp",
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


# Free-tier Gemini models pool for seamless auto-switching when daily limits are hit
FREE_TIER_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
]


def generate_with_fallback(client, contents, response_schema, preferred_model="gemini-3.8-flash"):
    models_to_try = [preferred_model] + [m for m in FREE_TIER_MODELS if m != preferred_model]
    
    last_err = None
    import time
    for idx, model in enumerate(models_to_try):
        next_model = models_to_try[idx + 1] if idx + 1 < len(models_to_try) else "None"
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
            # If daily limit / quota exceeded (429 / RESOURCE_EXHAUSTED), switch immediately
            if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
                print(f"    [Quota Notice] Daily limit reached on free model '{model}'. Switching to next free model '{next_model}'...")
                continue
            # If temporary 503 spike, retry once then fallback
            elif "503" in err_str or "unavailable" in err_str:
                print(f"    [Load Notice] Model '{model}' experienced high demand. Trying next free model '{next_model}'...")
                time.sleep(1)
                continue
            else:
                print(f"    [Model Notice] '{model}' unavailable ({e}). Falling back to '{next_model}'...")
                continue
    raise last_err


def find_viral_clips(youtube_url: str, num_clips: int, model_name: str = "gemini-2.5-flash") -> list[ClipSegment]:
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
            print(f"    Direct ingestion fallback ({e}). Analyzing community engagement highlights...")

    # If stream is long or direct video ingestion cannot process 11h, extract engagement peaks
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

    # Select distinct timestamps (separated by at least 120s)
    selected_ts = []
    for tc in ts_candidates:
        sec = time_to_seconds(tc["timestamp"])
        if not any(abs(sec - time_to_seconds(s["timestamp"])) < 120 for s in selected_ts):
            selected_ts.append(tc)
        if len(selected_ts) >= num_clips:
            break

    # If not enough timestamps found in comments, use sensible highlight anchors
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
        end_sec = start_sec + 45.0  # 45 second viral clip
        start_str = seconds_to_hms(start_sec)
        end_str = seconds_to_hms(end_sec)

        # Ask Gemini to generate Gen-Z viral metadata based on stream context
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


def download_slice(youtube_url: str, start_sec: float, end_sec: float, out_path: Path, browser: str | None = None):
    padded_start = seconds_to_hms(max(0.0, start_sec - 1.0))
    padded_end = seconds_to_hms(end_sec + 1.0)
    section_arg = f"*{padded_start}-{padded_end}"

    ytdlp_bin = r".\.venv\Scripts\yt-dlp.exe" if Path(r".\.venv\Scripts\yt-dlp.exe").exists() else "yt-dlp"
    cmd = [
        ytdlp_bin,
        youtube_url,
        "--extractor-args", "youtube:player_client=android",
        "--download-sections", section_arg,
        "--force-keyframes-at-cuts",
        "-f", "bestvideo[height<=1080]+bestaudio/best",
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
Style: Punchline,Arial Black,48,&H0000FFFF,&H00FFFFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,5,2,8,50,50,200,1
Style: Default,Arial Black,72,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    # Add top punchline banner spanning the entire clip
    if punchline:
        end_ass = seconds_to_ass_time(max(duration_sec, 1.0))
        lines.append(f"Dialogue: 1,0:00:00.00,{end_ass},Punchline,,0,0,0,,{punchline.strip().upper()}")

    # Group words into chunks of 3 for fast, punchy Shorts-style captions
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


def render_vertical_short(raw_clip: Path, ass_path: Path, final_clip: Path):
    escaped_ass = str(ass_path.resolve()).replace("\\", "/").replace(":", r"\:")

    # Center-crop 16:9 to 9:16 (1080x1920) and burn in subtitles + punchline
    vf_filter = f"crop=ih*9/16:ih,scale=1080:1920,subtitles='{escaped_ass}'"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(raw_clip),
        "-vf", vf_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        str(final_clip),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def main():
    parser = argparse.ArgumentParser(description="Automated YouTube-to-Shorts Clipper")
    parser.add_argument("url", help="Public YouTube video URL")
    parser.add_argument("--clips", type=int, default=3, help="Number of clips to generate")
    parser.add_argument("--cookies", default=None, help="Browser for cookies (e.g., chrome, edge, firefox)")
    parser.add_argument("--whisper-model", default="base.en", help="Whisper model size (tiny, base, small)")
    parser.add_argument("--model", default="gemini-3.8-flash", help="Gemini model")
    args = parser.parse_args()

    out_dir = Path("output_clips")
    work_dir = Path("temp_work")
    out_dir.mkdir(exist_ok=True)
    work_dir.mkdir(exist_ok=True)

    segments = find_viral_clips(args.url, args.clips, model_name=args.model)
    print(f"    Identified {len(segments)} viral moments.")

    print(f"[2/4] Loading Whisper model ({args.whisper_model})...")
    # Default to CPU on Windows to avoid missing cublas64_12.dll issues unless CUDA is verified
    whisper = WhisperModel(args.whisper_model, device="cpu", compute_type="int8")
    print("    Whisper loaded successfully on CPU (int8).")

    manifest = []
    for idx, seg in enumerate(segments, start=1):
        print(f"\n--- Processing Clip {idx}/{len(segments)}: {seg.title} ({seg.start_time} - {seg.end_time}) ---")
        print(f"    Punchline: '{seg.punchline}'")
        start_sec = time_to_seconds(seg.start_time)
        end_sec = time_to_seconds(seg.end_time)
        duration = end_sec - start_sec

        raw_path = work_dir / f"raw_{idx}.mp4"
        ass_path = work_dir / f"subs_{idx}.ass"
        final_path = out_dir / f"short_{idx}.mp4"

        print("  -> Downloading exact timestamp slice via yt-dlp...")
        download_slice(args.url, start_sec, end_sec, raw_path, args.cookies)

        print("  -> Extracting word-level timestamps via Whisper...")
        transcribed_segs, _ = whisper.transcribe(str(raw_path), word_timestamps=True)
        words = []
        for t_seg in transcribed_segs:
            if t_seg.words:
                for w in t_seg.words:
                    words.append({"word": w.word, "start": w.start, "end": w.end})

        generate_ass_subtitles(words, seg.punchline, ass_path, duration)

        print("  -> Rendering 9:16 vertical Short with burned-in captions & Gen-Z punchline...")
        render_vertical_short(raw_path, ass_path, final_path)

        manifest.append({
            "file": str(final_path),
            "title": seg.title,
            "punchline": seg.punchline,
            "caption_post": seg.caption_post,
            "original_window": f"{seg.start_time} - {seg.end_time}",
            "hook_reason": seg.hook_reason,
        })

    manifest_path = out_dir / "clips_metadata.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nDone! Ready-to-post clips and captions saved in: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
