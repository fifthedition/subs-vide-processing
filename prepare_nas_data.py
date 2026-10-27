#!/usr/bin/env python3
"""Copy private local data to a new NAS staging folder, preserving the original."""
import argparse
import os
from pathlib import Path
import shutil
import sqlite3


def prepare(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not (source / "data/studio.sqlite3").is_file():
        raise ValueError("Choose the existing breathwork-studio folder containing data/studio.sqlite3.")
    if destination.exists():
        raise ValueError("Choose a new destination folder, to avoid overwriting a NAS backup.")
    if source == destination or source in destination.parents:
        raise ValueError("Use a destination outside the existing app folder.")
    destination.mkdir(parents=True, mode=0o700)
    for path in (source / "data").iterdir():
        if path.name.startswith("studio.sqlite3") or path.name in ("setup-code",):
            continue
        target = destination / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        elif path.is_file():
            shutil.copy2(path, target)
    with sqlite3.connect(source / "data/studio.sqlite3") as old, sqlite3.connect(destination / "studio.sqlite3") as new:
        old.backup(new)
    archive = source / "archive/subtitles.json"
    if archive.is_file():
        shutil.copy2(archive, destination / "subtitles.json")
    for path in destination.rglob("*"):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    print(f"Private data copy ready: {destination}")
    print("Copy this folder's contents to the NAS data folder. Do not commit it or add it to a Docker image.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    options = parser.parse_args()
    os.umask(0o077)
    prepare(options.source, options.destination)
