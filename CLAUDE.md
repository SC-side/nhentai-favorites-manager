# Comic — Project Guide

## 1. Overview

A **personal nhentai collection manager**: a Flask web app that syncs your nhentai
favorites into a local SQLite database and lets you browse, rate, tag-filter, and annotate
them. Syncing reuses your existing, already-logged-in browser session through the
Chrome DevTools Protocol (CDP), so there is no manual cookie handling for the sync step.

> **Privacy note:** `config.json`, `collection.db`, `cover_cache/`, and `chrome-debug-profile/`
> contain personal data and/or credentials. They are excluded from version control via
> `.gitignore`. Copy `config.example.json` to `config.json` to set up your own credentials.

---

## 2. Project structure

```
Comic/
├── app.py                 # Flask backend: REST API + cover-image proxy
├── sync.py                # Sync script (Playwright + CDP)
├── config.py              # Config loading, cookie parsing, browser auto-detection
├── database.py            # SQLite wrapper (CRUD + filtering/sorting/pagination queries)
├── schema.sql             # DB schema (doujinshi, tags, doujinshi_tags)
├── config.json            # Config incl. cookies — DO NOT COMMIT (gitignored)
├── config.example.json    # Config template — copy to config.json
├── collection.db          # SQLite database (gitignored)
├── requirements.txt       # Python dependencies
├── start_chrome.sh        # Launch Chrome in debug mode (port 9222)
├── cover_cache/           # Locally cached cover images (gitignored)
├── chrome-debug-profile/  # Dedicated Chrome debug profile (gitignored)
├── templates/
│   └── index.html         # Frontend UI (React + Tailwind, via CDN)
└── static/
    └── style.css          # Dark-theme styles and animations
```

---

## 3. Tech stack

### Frontend
| Tech | Version | Purpose |
|---|---|---|
| React | 18 (CDN) | UI framework |
| Tailwind CSS | CDN | Styling |
| Lucide Icons | CDN | Icons |
| Babel Standalone | CDN | JSX compilation |

### Backend
| Tech | Version | Purpose |
|---|---|---|
| Python | 3.x | Runtime |
| Flask | ≥3.0 | Web framework |
| SQLite3 | built-in | Database |
| Playwright | ≥1.40 | CDP connection / browser automation |
| Requests | ≥2.31 | HTTP requests (cover-image proxy) |

> `beautifulsoup4` is listed in `requirements.txt` but is not currently imported anywhere;
> the HTML/JSON parsing is done in-browser via Playwright's `page.evaluate`.

---

## 4. Current status & known notes

### Done
- Flask REST API, SQLite schema, sync script (CDP integration), and frontend UI
- `sync.py` supports incremental sync (default) and full sync (`--full`)
- Cover images are proxied through the backend and cached locally in `cover_cache/`
- Opening a gallery launches it in Chrome

### Known notes
- `config.json` stores cookies (`cf_clearance`, `access_token`, `refresh_token`) in plain text — **do not commit it** (already gitignored)
- Flask runs with `debug=True` — local use only
- If nhentai returns 403 / 429, the sync script stops or backs off and prints a message
- `chrome-debug-profile/` is the Chrome debug profile; it can grow over time

---

## 5. How to run

### First-time setup

```bash
pip install -r requirements.txt
playwright install chromium          # install the Playwright browser
cp config.example.json config.json   # then fill in your cookies
```

### Step 1: Start Chrome (debug mode)

```bash
bash start_chrome.sh
```

This launches Chrome in debug mode on port 9222 using a dedicated profile
(`chrome-debug-profile/`). `sync.py` reuses this session's login state.
On first run, log in to nhentai.net in the Chrome window that opens.

### Step 2: Sync your collection

```bash
python sync.py            # incremental sync (stops after 2 consecutive pages with nothing new)
python sync.py --full     # full sync (scan all pages, rewrite favorite order, remove un-favorited)
python sync.py --help     # show all options
```

### Step 3: Start the web UI

```bash
python app.py
# Open your browser at: http://localhost:5001
```

---

## 6. Important settings

### Chrome debug mode (required by sync.py)
- CDP port: `9222`
- `start_chrome.sh` launches Chrome with the correct flags
- On startup `sync.py` checks whether port 9222 is reachable; if not, it prints instructions

### config.json
```json
{
  "cookies": {
    "cf_clearance": "...",
    "access_token": "...",
    "refresh_token": "..."
  },
  "user_agent": "Mozilla/5.0 ... Chrome/120 ...",
  "browser_path": "",
  "port": 5001,
  "request_delay": 1.5
}
```
- `cookies`: sent by the cover-image proxy (`/api/cover/...`) when fetching thumbnails from nhentai's CDN
- `browser_path`: when empty, `config.py` auto-detects (macOS: Chrome first, then Firefox)
- `port`: Flask web UI port
- `request_delay`: seconds to wait between requests during sync, to avoid rate limiting

### Browser auto-detection paths (config.py)
| Platform | Chrome default path |
|---|---|
| macOS | `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` |
| Windows | `C:\Program Files\Google\Chrome\Application\chrome.exe` |
| Linux | `google-chrome` (on PATH) |

### Database
- `collection.db` (SQLite, WAL mode)
- Tables: `doujinshi`, `tags`, `doujinshi_tags`
- `doujinshi` columns: `nhentai_id`, `title_ja`, `title_en`, `title_pretty`, `media_id`, `cover_type`, `pages`, `uploaded_at`, `favorited_at`, `rating`, `notes`

### Flask API endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Web UI |
| GET | `/api/doujinshi` | List collection (pagination, search, filtering) |
| PATCH | `/api/doujinshi/<id>/rating` | Update rating |
| PATCH | `/api/doujinshi/<id>/notes` | Update notes |
| GET | `/api/tags` | Tag list (by type) |
| GET | `/api/stats` | Collection statistics |
| GET | `/api/cover/<media_id>/<cover_type>` | Cover-image proxy (caches into `cover_cache/`) |
| GET | `/api/open/<id>` | Open the gallery in Chrome |
