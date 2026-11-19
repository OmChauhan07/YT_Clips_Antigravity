import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CONFIG_FILE = Path("config.json")


def load_config() -> dict:
    default_cfg = {
        "default_clips": 3,
        "default_layout": "split",
        "default_facecam": "top-right",
        "crf": 17,
        "preset": "slow",
        "models": [
            "gemini-4-hydrogen",
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
        ],
        "gdrive_upload": False,
        "gdrive_folder_id": os.getenv("GDRIVE_FOLDER_ID", ""),
        "local_cleanup": True,
        "check_interval_seconds": 300,
    }
    if CONFIG_FILE.exists():
        try:
            user_cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            default_cfg.update(user_cfg)
        except Exception as e:
            print(f"[Config] Warning: Failed to parse {CONFIG_FILE} ({e}). Using defaults.")
    return default_cfg


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"[Config] Updated and saved settings to {CONFIG_FILE.resolve()}")


def cleanup_local_temp(temp_dir: Path = Path("temp_work")):
    if temp_dir.exists():
        for item in temp_dir.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                print(f"[Cleanup] Notice: Could not remove {item.name}: {e}")
        print(f"[Cleanup] Cleaned temporary workspace files in {temp_dir.resolve()}.")


def upload_to_google_drive(files_to_upload: list[Path], folder_id: str | None = None) -> bool:
    """Upload rendered clips and metadata to Google Drive if credentials exist."""
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "service_account.json"
    if not Path(creds_path).exists() and not Path("credentials.json").exists():
        print("[GDrive] Notice: Google Drive credentials not found (set GOOGLE_APPLICATION_CREDENTIALS or provide service_account.json). Skipping cloud upload.")
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
            print("[GDrive] Please provide service_account.json or credentials.json to complete OAuth.")
            return False

        drive_service = build("drive", "v3", credentials=creds)

        for file_path in files_to_upload:
            if not file_path.exists():
                continue
            file_metadata = {"name": file_path.name}
            if folder_id:
                file_metadata["parents"] = [folder_id]

            mime_type = "video/mp4" if file_path.suffix == ".mp4" else "application/json"
            media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)

            print(f"[GDrive] Uploading {file_path.name} to Google Drive...")
            uploaded = drive_service.files().create(body=file_metadata, media_body=media, fields="id, name").execute()
            print(f"[GDrive] Uploaded {uploaded.get('name')} (ID: {uploaded.get('id')})")
        return True
    except Exception as e:
        print(f"[GDrive] Upload failed: {e}")
        return False


def run_pipeline_for_url(url: str, clips: int, layout: str, facecam: str, model: str | None, do_upload: bool, do_cleanup: bool):
    python_exe = sys.executable
    cmd = [
        python_exe, "clipper.py",
        url,
        "--clips", str(clips),
        "--layout", layout,
        "--facecam", facecam,
    ]
    if model:
        cmd.extend(["--model", model])

    print(f"\n==================================================")
    print(f"[AutoRun] Processing URL: {url}")
    print(f"[AutoRun] Clips: {clips} | Layout: {layout} | Facecam: {facecam}")
    print(f"==================================================")

    res = subprocess.run(cmd)
    if res.returncode != 0:
        print(f"[AutoRun] Pipeline returned non-zero code {res.returncode} for {url}")
        return

    out_dir = Path("output_clips")
    generated_files = list(out_dir.glob("short_*.mp4")) + [out_dir / "clips_metadata.json"]

    if do_upload:
        cfg = load_config()
        folder_id = cfg.get("gdrive_folder_id") or os.getenv("GDRIVE_FOLDER_ID")
        upload_to_google_drive(generated_files, folder_id)

    if do_cleanup:
        cleanup_local_temp(Path("temp_work"))


def main():
    parser = argparse.ArgumentParser(description="Unattended Auto-Runner for YT Clipping Pipeline")
    parser.add_argument("url", nargs="?", default=None, help="YouTube video or livestream URL")
    parser.add_argument("--batch-file", default=None, help="Text file containing one YouTube URL per line")
    parser.add_argument("--duration-hours", type=float, default=0.0, help="Run in continuous monitoring loop for X hours (e.g. 5.0)")
    parser.add_argument("--interval", type=int, default=None, help="Interval seconds between runs in unattended mode")
    parser.add_argument("--clips", type=int, default=None, help="Number of clips to generate")
    parser.add_argument("--layout", choices=["split", "blur", "zoom"], default=None, help="9:16 layout mode")
    parser.add_argument("--facecam", choices=["top-left", "top-right", "bottom-left", "bottom-right"], default=None)
    parser.add_argument("--model", default=None, help="Starting Gemini model")
    parser.add_argument("--gdrive-upload", action="store_true", default=None, help="Upload clips to Google Drive")
    parser.add_argument("--local-cleanup", action="store_true", default=None, help="Clean temp_work after processing")
    parser.add_argument("--save-config", action="store_true", help="Save specified CLI options as new defaults in config.json")
    args = parser.parse_args()

    cfg = load_config()

    clips = args.clips if args.clips is not None else cfg.get("default_clips", 3)
    layout = args.layout if args.layout is not None else cfg.get("default_layout", "split")
    facecam = args.facecam if args.facecam is not None else cfg.get("default_facecam", "top-right")
    interval = args.interval if args.interval is not None else cfg.get("check_interval_seconds", 300)
    do_upload = args.gdrive_upload if args.gdrive_upload is not None else cfg.get("gdrive_upload", False)
    do_cleanup = args.local_cleanup if args.local_cleanup is not None else cfg.get("local_cleanup", True)

    if args.save_config:
        cfg["default_clips"] = clips
        cfg["default_layout"] = layout
        cfg["default_facecam"] = facecam
        if args.gdrive_upload is not None:
            cfg["gdrive_upload"] = do_upload
        if args.local_cleanup is not None:
            cfg["local_cleanup"] = do_cleanup
        save_config(cfg)

    # Collect URLs
    urls = []
    if args.url:
        urls.append(args.url)
    elif args.batch_file and Path(args.batch_file).exists():
        for line in Path(args.batch_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)

    if not urls and args.duration_hours <= 0:
        print("Usage: python auto_run.py <YOUTUBE_URL> or --batch-file <urls.txt> or --duration-hours <hours>")
        return

    start_time = time.time()
    max_duration_sec = args.duration_hours * 3600 if args.duration_hours > 0 else 0

    print(f"[AutoRun] Starting unattended pipeline. Target clips: {clips}, Layout: {layout}")

    cycle = 1
    while True:
        print(f"\n--- [Cycle {cycle}] Starting at {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
        for u in urls:
            run_pipeline_for_url(u, clips, layout, facecam, args.model, do_upload, do_cleanup)

        if max_duration_sec <= 0:
            break

        elapsed = time.time() - start_time
        if elapsed >= max_duration_sec:
            print(f"[AutoRun] Target duration of {args.duration_hours} hours completed.")
            break

        print(f"[AutoRun] Cycle {cycle} finished. Sleeping {interval}s before next check...")
        time.sleep(interval)
        cycle += 1

    print("\n[AutoRun] Pipeline execution finished.")


if __name__ == "__main__":
    main()
