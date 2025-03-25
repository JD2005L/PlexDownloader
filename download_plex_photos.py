#!/usr/bin/env python3
"""
Download Plex Photos Script - V1.0
Author: James@Levac.net
Date: 03/24/2025

General usage:
    python download_plex_photos.py --base_url "https://your.plex.server:port" --token "YOUR_PLEX_TOKEN" --download_dir "./plex_photos" --verbose --download_delay 1

This script connects to your Plex server, finds photo sections and album directories,
and downloads each photo (skipping files that already exist locally). It provides simplified progress feedback.

You can also supply a list of album/directory names in INCLUDE_ALBUMS to only download those specific top-level albums.
Nested albums (sub-albums) inside an included album will be processed regardless of their title.
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

###############################################################################
# Only download top-level albums whose titles match one of these entries.
# If this list is empty, ALL top-level albums will be processed.
###############################################################################
INCLUDE_ALBUMS = [
    "Example1",
    "Example2",
    "Example3"
]

def sanitize_filename(name):
    """Replace disallowed filename characters with underscores."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def download_file(url, dest_path):
    """Download a file from the URL and save it to dest_path."""
    try:
        response = requests.get(url, stream=True, verify=False)
        response.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        logging.error("    Error downloading %s: %s", url, e)

def download_photo(photo, dest_dir, base_url, token, download_delay):
    """
    Given a photo element, extract its file part and download it.
    """
    ratingKey = photo.get('ratingKey') or photo.get('id')
    title = photo.get('title') or ratingKey
    title_sanitized = sanitize_filename(title)

    part = photo.find('.//Part')
    if part is None:
        logging.warning("    [No file part] %s (ratingKey: %s)", title, ratingKey)
        return

    part_key = part.get('key')
    container = part.get('container', 'jpg')
    if not part_key:
        logging.warning("    [No key] %s", title)
        return

    download_url = f"{base_url}{part_key}?download=1&X-Plex-Token={token}"
    filename = f"{ratingKey}_{title_sanitized}.{container}"
    dest_path = os.path.join(dest_dir, filename)

    if os.path.exists(dest_path):
        logging.info("    [Skipping existing file] %s", filename)
        return

    download_file(download_url, dest_path)
    logging.info("    [Downloaded] %s", filename)
    if download_delay > 0:
        time.sleep(download_delay)

def process_album(album_url, album_title, base_url, token, album_dir, download_delay):
    logging.info("")
    logging.info("  Album: %s", album_title)

    try:
        r = requests.get(album_url, headers={'X-Plex-Token': token}, verify=False)
        r.raise_for_status()
    except Exception as e:
        logging.error("    Error accessing album '%s': %s", album_title, e)
        return

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        logging.error("    XML parse error in album '%s': %s", album_title, e)
        return

    # Process photos in the current album.
    photos = root.findall('./Photo')
    if not photos:
        photos = root.findall('./Metadata[@type="photo"]')
    num_photos = len(photos)
    logging.info("    Total photos in '%s': %d", album_title, num_photos)
    for i, photo in enumerate(photos, start=1):
        logging.info("    Photo %d of %d", i, num_photos)
        download_photo(photo, album_dir, base_url, token, download_delay)

    # Recursively process any nested sub-albums.
    sub_albums = root.findall('./Directory')
    if sub_albums:
        logging.info("    Found %d nested album(s) in '%s'", len(sub_albums), album_title)
    for sub in sub_albums:
        sub_album_title = sub.get("title", "untitled")
        sub_album_key = sub.get("key")
        sub_album_dir = os.path.join(album_dir, sanitize_filename(sub_album_title))
        os.makedirs(sub_album_dir, exist_ok=True)
        sub_album_url = f"{base_url}{sub_album_key}?includeChildren=1&X-Plex-Token={token}"
        process_album(sub_album_url, sub_album_title, base_url, token, sub_album_dir, download_delay)

def main():
    parser = argparse.ArgumentParser(description="Download all photos from a Plex photo section and its albums.")
    parser.add_argument("--base_url", required=True, help="Base Plex URL (e.g., https://your.plex.server:port)")
    parser.add_argument("--token", required=True, help="Your Plex token")
    parser.add_argument("--download_dir", default="./plex_photos", help="Directory to save downloaded photos")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--download_delay", default=0, type=float, help="Delay between downloads in seconds")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    base_url = args.base_url.rstrip("/")
    token = args.token
    download_dir = args.download_dir
    download_delay = args.download_delay
    os.makedirs(download_dir, exist_ok=True)

    logging.info("\nRequesting library sections...")
    sections_url = f"{base_url}/library/sections?X-Plex-Token={token}"
    try:
        sections_r = requests.get(sections_url, headers={'X-Plex-Token': token}, verify=False)
        sections_r.raise_for_status()
    except Exception as e:
        logging.error("Error retrieving library sections: %s", e)
        return

    try:
        sections_root = ET.fromstring(sections_r.content)
    except ET.ParseError as e:
        logging.error("Failed to parse sections XML: %s", e)
        return

    # Find photo sections (where type is "photo").
    photo_sections = [d for d in sections_root.findall("Directory") if d.get("type") == "photo"]
    if not photo_sections:
        logging.error("No photo sections found!")
        return

    for section in photo_sections:
        section_key = section.get("key")
        section_title = section.get("title", "untitled")
        section_dir = os.path.join(download_dir, sanitize_filename(section_title))
        os.makedirs(section_dir, exist_ok=True)

        logging.info("\nSection: %s", section_title)
        all_url = f"{base_url}/library/sections/{section_key}/all?X-Plex-Token={token}"
        try:
            items_r = requests.get(all_url, headers={'X-Plex-Token': token}, verify=False)
            items_r.raise_for_status()
        except Exception as e:
            logging.error("Error retrieving section items: %s", e)
            continue

        try:
            items_root = ET.fromstring(items_r.content)
        except ET.ParseError as e:
            logging.error("Error parsing section items XML: %s", e)
            continue

        # Process top-level photos (if any).
        top_photos = items_root.findall('.//Photo')
        if not top_photos:
            top_photos = items_root.findall('.//Metadata[@type="photo"]')
        if top_photos:
            logging.info("  Top-level photos: %d", len(top_photos))
            for i, photo in enumerate(top_photos, start=1):
                logging.info("    Photo %d of %d", i, len(top_photos))
                download_photo(photo, section_dir, base_url, token, download_delay)

        # Process top-level album directories.
        album_dirs = items_root.findall(".//Directory")
        if album_dirs:
            logging.info("  Album directories found: %d", len(album_dirs))

        for album in album_dirs:
            album_key = album.get("key")
            album_title = album.get("title", "untitled")

            # Only filter top-level albums.
            if INCLUDE_ALBUMS and album_title not in INCLUDE_ALBUMS:
                logging.info("  Skipping album (not in INCLUDE_ALBUMS): %s", album_title)
                continue

            album_subdir = os.path.join(section_dir, sanitize_filename(album_title))
            os.makedirs(album_subdir, exist_ok=True)
            album_url = f"{base_url}{album_key}?includeChildren=1&X-Plex-Token={token}"
            process_album(album_url, album_title, base_url, token, album_subdir, download_delay)

if __name__ == "__main__":
    main()
