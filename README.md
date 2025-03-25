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
