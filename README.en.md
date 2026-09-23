# BookCloud for KOReader

**Find your next book without leaving your e-reader.**

Search by title or author, choose an edition, download it, and open it in KOReader. BookCloud brings a source-based book discovery workflow to Kobo, with a companion web interface for managing your sources.

[简体中文](README.md) · [Downloads](https://github.com/boboyu1215/koreader-bookcloud/releases) · [Installation guide (Chinese)](docs/INSTALL.md) · [Report an issue](https://github.com/boboyu1215/koreader-bookcloud/issues)

> Public beta. Requires KOReader and a self-hosted HTTPS backend. No hosted search service or third-party source bundle is included. This is not a full Legado implementation.

<p align="center"><img src="docs/images/kobo-search.jpg" width="350" alt="Real Kobo device showing author search results and edition counts"></p>

## Features

- Search configured sources by title or author.
- Group results into works and retain available editions.
- Download EPUB, PDF or TXT files and read them offline.
- Two-line titles with smaller metadata; hold to see full titles, and natural volume ordering.
- On-device setup using a short-lived pairing code.
- Bounded retries for transient upstream errors, file preparation before transfer and edition switching after failure.
- Recent searches and a list of downloaded books.
- Web-based source configuration, import, export and download testing.
- OPDS, Gutendex, custom catalogs and a limited subset of static Legado text rules.

## Quick start

1. Clone this repository on your server and run `docker compose up -d --build`.
2. Expose the service over HTTPS. An optional Caddy configuration is included: set `BOOKCLOUD_HOST` in `.env`, point its DNS to your server, and run `docker compose -f compose.yaml -f compose.https.yaml up -d --build`. Ports 80 and 443 must be available.
3. Read the device credential with `docker compose exec bookcloud cat /data/device-token`. Keep it private. The separate `/data/admin-token` is for the web admin interface.
4. Download the plugin ZIP from Releases. Extract `bookcloud.koplugin` into KOReader's `plugins` directory.
5. Generate a pairing code in the web admin interface. On the reader, enter your HTTPS service URL and the 8-digit code (single use, expires after 5 minutes). Advanced settings also support manual device credentials and a custom download directory. Existing configuration files remain supported.
6. Restart KOReader and open **云书库 · 搜书** from its menu. ZenOS is optional.

On Kobo, the usual KOReader path is `.adds/koreader`, and the default download directory is `/mnt/onboard/book/云书库`. Adjust both for your installation.

## Current limits

The primary environment is Kobo with KOReader; the existing installation used KOReader 2026.07.1. The photo demonstrates the search UI, not a complete device compatibility certification. Other devices have not been verified. The plugin UI is currently Chinese.

Search returns the first batch from each remote source. Work grouping is heuristic. Files are limited to 50 MB. Static-source books are prepared as EPUBs before download. JavaScript, WebView, XPath, authenticated sources and paid chapters are unsupported. There is no download resume or on-device background queue.

## Contributing

Please share your device model, KOReader version, BookCloud version and reproduction steps in an issue. Remove credentials before posting logs. See [development instructions](CONTRIBUTING.md).

If BookCloud makes your reading workflow easier, a Star helps other readers discover it.

Licensed under [AGPL-3.0-or-later](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md). This is an independent community project, unaffiliated with Kobo/Rakuten, KOReader or Legado. Only connect content you are authorized to access.
