# nhentai Favorites Manager

A self-hosted web app for browsing, organizing, and rating your nhentai favorites.
Syncing reuses your existing, already-logged-in Chrome session via the Chrome
DevTools Protocol (CDP) — no manual cookie copying required.

## Features

- Sync your nhentai favorites into a local SQLite database (incremental or full sync)
- Browse your collection with full-text search, tag filters, sorting, and pagination
- Rate works (1–3 stars) and add personal notes
- Local cover image caching, proxied through the backend
- One-click open in Chrome
- Dark-themed React UI

## Tech Stack

- **Backend:** Python 3, Flask, SQLite
- **Sync:** Playwright (connects to Chrome via CDP, reuses your logged-in session)
- **Frontend:** React 18 + Tailwind CSS (via CDN), Lucide icons

## Prerequisites

- Python 3.9+
- Google Chrome
- An nhentai.net account with some favorites

## Setup

```bash
git clone https://github.com/SC-side/nhentai-favorites-manager.git
cd nhentai-favorites-manager

pip install -r requirements.txt          # Flask, Playwright, Requests
cp config.example.json config.json
```

> **Note:** you do *not* need to run `playwright install chromium`. Syncing connects to
> your own Chrome via CDP and never launches Playwright's bundled browser. You can also
> leave `config.json` as-is for now — cookies are only needed if cover thumbnails fail to
> load in the web UI (see [Configuration](#configuration)).

## Usage

### 1. Start Chrome in debug mode

**macOS:**

```bash
bash start_chrome.sh
```

**Windows / Linux** — `start_chrome.sh` is macOS-only, so launch Chrome manually
(close your other Chrome windows first):

```bash
# Windows (PowerShell)
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="chrome-debug-profile"

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome-debug-profile
```

This opens a dedicated Chrome profile with remote debugging on port 9222. On first run,
log in to nhentai.net in that window. **Keep this Chrome window open** while syncing —
`sync.py` connects to it.

### 2. Sync your favorites

With the debug Chrome from step 1 still running:

```bash
python sync.py                 # incremental sync (stops after 2 pages with nothing new)
python sync.py --full          # full sync (also removes un-favorited works, reorders by favorite time)
python sync.py --max-pages 5   # limit the scan to N pages (useful for testing)
python sync.py --help          # show all options
```

### 3. Launch the web UI

```bash
python app.py
```

Then open **http://localhost:5001** in your browser.

## Configuration

Copy `config.example.json` to `config.json` and adjust as needed:

| Key | Description |
|---|---|
| `cookies` | *(optional)* Only used by the cover-image proxy — see [Cookies](#cookies-optional) below |
| `user_agent` | User-Agent header sent with cover requests |
| `browser_path` | Override path to Chrome/Firefox; leave empty for auto-detection |
| `port` | Port for the Flask web UI (default `5001`) |
| `request_delay` | Seconds to wait between requests during sync, to avoid rate limiting |

### Cookies (optional)

Syncing does **not** need cookies — it uses your logged-in Chrome session. The cookies in
`config.json` are only used by the web UI's cover-image proxy. If cover thumbnails fail to
load, add your nhentai cookies:

1. Log in to nhentai.net, press **F12** → **Network** tab → refresh the page.
2. Click any request → **Headers** → **Request Headers**, and copy the value of the **Cookie:** field.
3. Paste at least `cf_clearance` and `access_token` into the `cookies` object in `config.json`.

## Project Structure

```
.
├── app.py                 # Flask backend (REST API + cover-image proxy)
├── sync.py                # Sync script (Playwright + CDP)
├── config.py              # Config loading & browser auto-detection
├── database.py            # SQLite access layer
├── schema.sql             # Database schema
├── start_chrome.sh        # Launches Chrome in debug mode
├── templates/index.html   # Frontend UI (React)
└── static/style.css       # Styles
```

## Privacy

`config.json`, `collection.db`, `cover_cache/`, and `chrome-debug-profile/` are all
gitignored — your collection, cookies, and browsing session never leave your machine.

Flask runs in debug mode and binds to `0.0.0.0` by default, intended for local/LAN
use only. Don't expose it to the public internet.

## Disclaimer

This is a personal tool for organizing your own nhentai favorites. It does not host,
distribute, or download any content beyond what your account already has access to.
Use it in accordance with nhentai's Terms of Service.
