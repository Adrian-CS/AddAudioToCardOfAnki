#!/usr/bin/env python3
"""
Package the addon directory as a .ankiaddon file.

Usage:
    python build.py
"""

import os
import zipfile

ADDON_DIR = "addon"
OUTPUT = "AddAudioToCards.ankiaddon"


def build():
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ADDON_DIR):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if fname.endswith(".pyc"):
                    continue
                filepath = os.path.join(root, fname)
                arcname = os.path.relpath(filepath, ADDON_DIR)
                zf.write(filepath, arcname)
                print(f"  + {arcname}")

    print(f"\nBuilt: {OUTPUT}")
    print("Install: Anki > Tools > Add-ons > Install from file...")


if __name__ == "__main__":
    build()
