"""Download the latest official Stockfish (Windows x86-64) into engine/.

Source: https://github.com/official-stockfish/Stockfish/releases (GPL-3.0)
Other systems: install Stockfish yourself and set STOCKFISH_PATH, or put it on your PATH.
"""
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
TARGET = HERE / "engine" / "stockfish.exe"
API = "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest"


def main():
    if TARGET.exists():
        print(f"Stockfish is already installed: {TARGET}")
        return
    if sys.platform != "win32":
        sys.exit("This script downloads the Windows version. On Linux/macOS install Stockfish with your package "
                 "manager (e.g. 'brew install stockfish' or 'apt install stockfish').")
    req = urllib.request.Request(API, headers={"User-Agent": "chess-coach-setup"})
    with urllib.request.urlopen(req, timeout=30) as r:
        release = json.load(r)
    assets = [a for a in release["assets"] if "windows-x86-64" in a["name"] and a["name"].endswith(".zip")]
    # the "universal" build runs on every 64-bit PC; otherwise take the plain x86-64 build
    asset = next((a for a in assets if "universal" in a["name"]), None) or \
        next((a for a in assets if a["name"] == "stockfish-windows-x86-64.zip"), None) or (assets[0] if assets else None)
    if asset is None:
        sys.exit("Could not find a Windows build of Stockfish. Download it from https://stockfishchess.org/download/ "
                 "and put stockfish.exe into the 'engine' folder.")
    print(f"Downloading {release['tag_name']}: {asset['name']} ({asset['size'] // 1_000_000} MB) ...")
    with urllib.request.urlopen(asset["browser_download_url"], timeout=300) as r:
        data = r.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        exe = next(n for n in z.namelist() if n.lower().endswith(".exe"))
        TARGET.parent.mkdir(exist_ok=True)
        TARGET.write_bytes(z.read(exe))
    print(f"Stockfish installed: {TARGET}")


if __name__ == "__main__":
    main()
