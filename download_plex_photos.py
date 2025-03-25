#!/usr/bin/env python3
"""
Download Plex Photos Script
Author: James@Levac.net
Version: 1.0
Date: 03/25/2025

General usage:
    python download_plex_photos.py --base_url "https://your.plex.server:port" \
                                   --token "YOUR_PLEX_TOKEN" \
                                   --download_dir "./plex_photos" \
                                   --verbose \
                                   --download_delay 1

This script connects to your Plex server, finds photo sections and album directories,
and downloads each photo (skipping files that already exist locally). It provides
simplified progress feedback.

You can also supply a list of album/directory names in INCLUDE_ALBUMS to only
download those specific top-level albums. Nested albums (sub-albums) inside
an included top-level album will still be processed regardless of their title.
"""

import os
import re
import time
import requests
import urllib3
import xml.etree.ElementTree as ET
import argparse
import logging

# Disable SSL warnings for self-signed certificates.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Suppress low-level requests/urllib3 logs:
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

###############################################################################
# Only download top-level albums whose titles match one of these entries.
# If this list is empty, ALL top-level albums will be processed.
# Nested sub-albums are always processed if their parent is included.
###############################################################################
INCLUDE_ALBUMS = [
    # Example: "2022-01", "2022-02", ...
]

def sanitize_filename(name: str) -> str:
    """Replace disallowed filename characters with underscores."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def build_download_url(base_url: str, part_key: str, token: str) -> str:
    """Construct the download URL for a photo part."""
    return f"{base_url}{part_key}?download=1&X-Plex-Token={token}"

def gather_album_photos(album_title: str,
                        album_url: str,
                        album_dir: str,
                        base_url: str,
                        token: str) -> list:
    """
    Recursively gather all photos from a given album (and any sub-albums).
    Returns a list of dicts, each representing a single photo to be downloaded:
      [
        {
          "album_title": str,
          "local_path": str,        # Full path to local file
          "filename": str,          # The filename alone
          "download_url": str,      # URL from which to download
        },
        ...
      ]
    """
    results = []

    # Request album metadata
    try:
        r = requests.get(album_url, headers={'X-Plex-Token': token}, verify=False)
        r.raise_for_status()
    except Exception as e:
        logging.info(f"ERROR: cannot access album '{album_title}' -> {e}")
        return results

    # Parse XML
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        logging.info(f"ERROR: XML parse in album '{album_title}' -> {e}")
        return results

    # --- Gather photos in the current album ---
    photos = root.findall('./Photo')
    if not photos:
        photos = root.findall('./Metadata[@type="photo"]')
    for photo in photos:
        ratingKey = photo.get('ratingKey') or photo.get('id')
        photo_title = photo.get('title') or ratingKey
        part = photo.find('.//Part')
        if part is None:
            continue
        part_key = part.get('key')
        if not part_key:
            continue
        container = part.get('container', 'jpg')

        safe_title = sanitize_filename(photo_title)
        filename = f"{ratingKey}_{safe_title}.{container}"
        local_path = os.path.join(album_dir, filename)

        if os.path.exists(local_path):
            logging.info(f"SKIP (exists) {os.path.relpath(local_path, album_dir)}")
            continue

        download_url = build_download_url(base_url, part_key, token)
        logging.info(f"QUEUED {os.path.relpath(local_path, album_dir)}")
        results.append({
            "album_title": album_title,
            "filename": filename,
            "local_path": local_path,
            "download_url": download_url,
        })

    # --- Recursively gather any nested sub-albums ---
    sub_albums = root.findall('./Directory')
    for sub in sub_albums:
        sub_title = sub.get("title", "untitled")
        sub_key = sub.get("key")
        sub_dir = os.path.join(album_dir, sanitize_filename(sub_title))
        os.makedirs(sub_dir, exist_ok=True)
        sub_url = f"{base_url}{sub_key}?includeChildren=1&X-Plex-Token={token}"
        results.extend(gather_album_photos(sub_title, sub_url, sub_dir, base_url, token))

    return results

def gather_section_photos(section_title: str,
                          section_root: ET.Element,
                          section_dir: str,
                          base_url: str,
                          token: str) -> list:
    """
    Gather top-level photos and top-level album directories (recursively),
    respecting INCLUDE_ALBUMS filtering only for top-level albums.
    """
    tasks = []

    # Gather top-level photos (if any)
    top_photos = section_root.findall('.//Photo')
    if not top_photos:
        top_photos = section_root.findall('.//Metadata[@type="photo"]')
    for photo in top_photos:
        ratingKey = photo.get('ratingKey') or photo.get('id')
        photo_title = photo.get('title') or ratingKey
        part = photo.find('.//Part')
        if part is None:
            continue
        part_key = part.get('key')
        if not part_key:
            continue
        container = part.get('container', 'jpg')

        safe_title = sanitize_filename(photo_title)
        filename = f"{ratingKey}_{safe_title}.{container}"
        local_path = os.path.join(section_dir, filename)
        if os.path.exists(local_path):
            logging.info(f"SKIP (exists) {os.path.relpath(local_path, section_dir)}")
            continue

        download_url = build_download_url(base_url, part_key, token)
        logging.info(f"QUEUED {os.path.relpath(local_path, section_dir)}")
        tasks.append({
            "album_title": section_title,  # top-level photo in the section
            "filename": filename,
            "local_path": local_path,
            "download_url": download_url,
        })

    # Gather top-level album directories
    album_dirs = section_root.findall(".//Directory")
    for album in album_dirs:
        album_key = album.get("key")
        album_title = album.get("title", "untitled")

        # Only filter top-level albums.
        if INCLUDE_ALBUMS and album_title not in INCLUDE_ALBUMS:
            logging.info(f"SKIP (album not in INCLUDE_ALBUMS) {album_title}")
            continue

        album_subdir = os.path.join(section_dir, sanitize_filename(album_title))
        os.makedirs(album_subdir, exist_ok=True)
        album_url = f"{base_url}{album_key}?includeChildren=1&X-Plex-Token={token}"
        tasks.extend(gather_album_photos(album_title, album_url, album_subdir, base_url, token))
    return tasks

def download_tasks(tasks: list, download_delay: float, download_dir: str):
    """
    Given a list of download tasks (each with album_title, filename, local_path, download_url),
    download them one by one, showing progress logs that include the album/sub-album path starting
    from the top-level album (i.e. skipping the base download directory).
    """
    total = len(tasks)
    for i, task in enumerate(tasks, start=1):
        # Remove the base download directory so the path starts with the album folder.
        rel_full = os.path.relpath(task["local_path"], download_dir)
        parts = os.path.normpath(rel_full).split(os.sep)
        display_path = os.path.join(*parts[1:]) if len(parts) > 1 else rel_full
        logging.info(f"Downloading {i} of {total} - {display_path}")
        try:
            response = requests.get(task["download_url"], stream=True, verify=False)
            response.raise_for_status()
            with open(task["local_path"], 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        except Exception as e:
            logging.info(f"ERROR downloading {display_path} -> {e}")
        else:
            if download_delay > 0:
                time.sleep(download_delay)

def main():
    parser = argparse.ArgumentParser(description="Download all photos from a Plex photo section and its albums.")
    parser.add_argument("--base_url", required=True, help="Base Plex URL (e.g., https://your.plex.server:port)")
    parser.add_argument("--token", required=True, help="Your Plex token")
    parser.add_argument("--download_dir", default="./plex_photos", help="Directory to save downloaded photos")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--download_delay", default=0, type=float,
                        help="Delay between downloads in seconds (can be fractional)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    base_url = args.base_url.rstrip("/")
    token = args.token
    download_dir = args.download_dir
    download_delay = args.download_delay
    os.makedirs(download_dir, exist_ok=True)

    logging.info("Requesting library sections...")
    sections_url = f"{base_url}/library/sections?X-Plex-Token={token}"
    try:
        sections_r = requests.get(sections_url, headers={'X-Plex-Token': token}, verify=False)
        sections_r.raise_for_status()
    except Exception as e:
        logging.info(f"ERROR: retrieving library sections -> {e}")
        return

    try:
        sections_root = ET.fromstring(sections_r.content)
    except ET.ParseError as e:
        logging.info(f"ERROR: parsing sections XML -> {e}")
        return

    # Find photo sections (where type is "photo").
    photo_sections = [d for d in sections_root.findall("Directory") if d.get("type") == "photo"]
    if not photo_sections:
        logging.info("No photo sections found!")
        return

    all_tasks = []
    for section in photo_sections:
        section_key = section.get("key")
        section_title = section.get("title", "untitled")
        section_dir = os.path.join(download_dir, sanitize_filename(section_title))
        os.makedirs(section_dir, exist_ok=True)

        logging.info(f"\nSection: {section_title}")
        all_url = f"{base_url}/library/sections/{section_key}/all?X-Plex-Token={token}"
        try:
            items_r = requests.get(all_url, headers={'X-Plex-Token': token}, verify=False)
            items_r.raise_for_status()
        except Exception as e:
            logging.info(f"ERROR: retrieving items for section '{section_title}' -> {e}")
            continue

        try:
            items_root = ET.fromstring(items_r.content)
        except ET.ParseError as e:
            logging.info(f"ERROR: parsing items XML in section '{section_title}' -> {e}")
            continue

        section_tasks = gather_section_photos(section_title, items_root, section_dir, base_url, token)
        all_tasks.extend(section_tasks)

    total_to_download = len(all_tasks)
    if total_to_download == 0:
        logging.info("\nAll files already exist locally. Nothing to download.")
        return

    logging.info(f"\nTotal files to download: {total_to_download}\n")
    download_tasks(all_tasks, download_delay, download_dir)

if __name__ == "__main__":
    main()
