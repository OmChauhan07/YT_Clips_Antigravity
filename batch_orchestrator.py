import os
import subprocess
import sys
import time
from pathlib import Path

SOURCES = [
    {
        "name": "Kai Cenat Live",
        "url": "https://www.youtube.com/live/VZqAPdUvqnQ",
        "folder": "output_clips/Kai_Cenat_Live",
        "accent": "&H00008CFF&",  # Neon Orange
        "clips": 12,
    },
    {
        "name": "Lacy",
        "url": "https://www.youtube.com/live/5Oru4XpAYZw",
        "folder": "output_clips/Lacy",
        "accent": "&H0000FFFF&",  # Electric Yellow
        "clips": 10,
    },
    {
        "name": "Mythpat",
        "url": "https://www.youtube.com/live/LMbea5SozeM",
        "folder": "output_clips/Mythpat",
        "accent": "&H00FFFF00&",  # Cyan / Light Blue
        "clips": 10,
    },
]


def run_batch():
    python_exe = sys.executable
    print(f"==========================================================")
    print(f"🎬 STARTING BATCH CLIPPING PIPELINE (3 TARGET STREAMS)")
    print(f"   Hours = Clips ratio active | Layout: BLUR | NSFW Shield: ON")
    print(f"   Dedicated folder per source & distinct Gen-Z color styling")
    print(f"==========================================================\n")

    for idx, s in enumerate(SOURCES, start=1):
        print(f"\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
        print(f"[{idx}/{len(SOURCES)}] Processing: {s['name']}")
        print(f"     URL: {s['url']}")
        print(f"     Target clips: {s['clips']} | Color: {s['accent']}")
        print(f"     Destination: {s['folder']}")
        print(f"<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<\n")

        cmd = [
            python_exe, "-u", "clipper.py",
            s["url"],
            "--clips", str(s["clips"]),
            "--layout", "blur",
            "--out-dir", s["folder"],
            "--accent-color", s["accent"],
        ]

        res = subprocess.run(cmd)
        if res.returncode == 0:
            print(f"\n[DONE] Successfully rendered all clips for {s['name']} in {s['folder']}!\n")
        else:
            print(f"\n[NOTICE] Stream {s['name']} exited with code {res.returncode}.\n")

    print("\n==========================================================")
    print("🎉 BATCH CLIPPING PIPELINE COMPLETED FOR ALL 3 STREAMS!")
    print("==========================================================")


if __name__ == "__main__":
    run_batch()
