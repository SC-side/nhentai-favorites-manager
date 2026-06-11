#!/usr/bin/env python3
"""nhentai Favorites sync script (Playwright + CDP version)

Usage:
  python sync.py                   # Incremental sync (stops after 2 consecutive pages with no new items)
  python sync.py --full            # Force a full sync (no early stop; rewrites favorited_at to nhentai order)
  python sync.py --max-pages 10   # Scan at most the first 10 pages (for testing)
  python sync.py --help            # Show available options

Connects to a local Chrome via the Chrome DevTools Protocol (CDP),
reusing the already-logged-in session so no manual cookie setup is needed.

The script auto-starts Chrome (with --remote-debugging-port=9222);
if Chrome is already running in debug mode it connects directly.
"""

import json
import os
import sys
import time
import re
import urllib.request
import urllib.error

from playwright.sync_api import sync_playwright

from config import load_config
from database import (
    init_db,
    get_existing_ids,
    insert_doujinshi,
    delete_doujinshi_batch,
    update_favorited_order,
)

NHENTAI_BASE = "https://nhentai.net"
NHENTAI_API = "https://nhentai.net/api/v2/gallery"

CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}"


def is_chrome_debug_running():
    """Check whether a Chrome instance is already running on the debug port."""
    try:
        req = urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2)
        req.close()
        return True
    except (urllib.error.URLError, OSError):
        return False


def ensure_chrome_debug():
    """Ensure Chrome is running in debug mode; otherwise print instructions and exit."""
    if is_chrome_debug_running():
        print(f"✓ Connected to Chrome debug port ({CDP_URL})\n")
        return

    print("=" * 55)
    print("  [ACTION NEEDED] Chrome is not running in debug mode yet")
    print("=" * 55)
    print()
    print("First, run the following command in another Terminal tab to start Chrome:")
    print()
    print("  bash start_chrome.sh")
    print()
    print("Once it's running, come back and run python3 sync.py")
    print()
    sys.exit(0)


def fetch_favorites_page(page, page_num):
    """Navigate to a favorites page and extract gallery IDs."""
    url = f"{NHENTAI_BASE}/favorites/?page={page_num}"
    resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)

    if resp and resp.status == 403:
        print("\n[ERROR] 403 Forbidden - login session may have expired; re-login in the debug Chrome window, then rerun sync.py")
        sys.exit(1)

    if resp and resp.status == 429:
        print("\n[WARNING] 429 Too Many Requests - waiting 30 seconds before retrying...")
        time.sleep(30)
        return fetch_favorites_page(page, page_num)

    # Extract gallery IDs via JS in the browser context
    gallery_ids = page.evaluate("""() => {
        const ids = [];
        // Primary selector
        document.querySelectorAll('div.gallery-favorite a[href*="/g/"]').forEach(a => {
            const m = a.href.match(/\\/g\\/(\\d+)\\//);
            if (m) ids.push(parseInt(m[1]));
        });
        // Fallback
        if (ids.length === 0) {
            document.querySelectorAll('a[href*="/g/"]').forEach(a => {
                const m = a.href.match(/\\/g\\/(\\d+)\\//);
                if (m) {
                    const id = parseInt(m[1]);
                    if (!ids.includes(id)) ids.push(id);
                }
            });
        }
        return ids;
    }""")

    # Detect total pages
    total_pages = page.evaluate("""() => {
        const last = document.querySelector('a.last');
        if (last) {
            const m = last.href.match(/page=(\\d+)/);
            if (m) return parseInt(m[1]);
        }
        let max = 1;
        document.querySelectorAll('a.page').forEach(a => {
            const n = parseInt(a.textContent.trim());
            if (!isNaN(n) && n > max) max = n;
        });
        return max;
    }""")

    return gallery_ids, total_pages


def fetch_gallery_metadata(page, gallery_id):
    """Browse nhentai.net/g/{id}/ directly and read metadata from the page's embedded window._gallery.

    Originally this used the API endpoint (/api/v2/gallery/{id}), but that endpoint
    requires special authentication and returns 404. Instead we open the web page directly;
    nhentai's gallery page bundles the full data into the page.
    """
    url = f"{NHENTAI_BASE}/g/{gallery_id}/"
    resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)

    if resp and resp.status == 404:
        # Genuinely removed from nhentai
        return "DELETED"

    if resp and resp.status == 429:
        print(f"  [WARNING] #{gallery_id} 429 Rate limited - waiting 30 seconds before retrying...")
        time.sleep(30)
        return fetch_gallery_metadata(page, gallery_id)

    if resp and resp.status == 403:
        print(f"  [ERROR] #{gallery_id} 403 Forbidden - please make sure Chrome is logged in to nhentai.net")
        return None

    if resp and resp.status not in (200,):
        print(f"  [WARNING] #{gallery_id} unexpected status code {resp.status}")
        return None

    # nhentai has switched to SvelteKit; the data is embedded inside a <script> tag,
    # in the form {"status":200, "body": "{...gallery JSON...}"}
    gallery_data = page.evaluate("""() => {
        const scripts = Array.from(document.querySelectorAll('script'));
        for (const s of scripts) {
            try {
                const wrapper = JSON.parse(s.textContent.trim());
                if (wrapper.status === 200 && typeof wrapper.body === 'string') {
                    const body = JSON.parse(wrapper.body);
                    // Make sure it's gallery data (has id and media_id)
                    if (body.id && body.media_id && body.title) {
                        return body;
                    }
                }
            } catch(e) {}
        }
        return null;
    }""")

    if gallery_data is None:
        print(f"  [ERROR] #{gallery_id} gallery data not found; the page structure may have changed again")
        # Print the first two scripts to help debugging
        scripts = page.evaluate("""() =>
            Array.from(document.querySelectorAll('script'))
                .map(s => s.textContent.trim()).filter(t => t.length > 0).slice(0,2)
        """)
        for i, s in enumerate(scripts):
            print(f"  [DEBUG] script[{i}]: {s[:200]}")
        return None

    return gallery_data


def parse_gallery_data(api_data):
    """Parse nhentai API response into our database format."""
    titles = api_data.get("title", {})
    images = api_data.get("images", {})
    cover = images.get("cover", {})
    cover_type_key = cover.get("t", "j")

    doujinshi = {
        "nhentai_id": api_data["id"],
        "title_ja": titles.get("japanese", "") or "",
        "title_en": titles.get("english", "") or "",
        "title_pretty": titles.get("pretty", "") or "",
        "media_id": str(api_data.get("media_id", "")),
        "cover_type": cover_type_key,
        "pages": api_data.get("num_pages", 0),
        "uploaded_at": api_data.get("upload_date"),
        "favorited_at": int(time.time()),
        "rating": None,
        "notes": "",
    }

    tags = []
    for tag in api_data.get("tags", []):
        tags.append({
            "name": tag["name"],
            "type": tag["type"],
            "count": tag.get("count", 0),
        })

    return doujinshi, tags


def sync_favorites(full_sync=False, max_pages=None):
    config = load_config()
    delay = config.get("request_delay", 1.5)

    init_db()

    existing_ids = get_existing_ids()
    print(f"Database already contains {len(existing_ids)} works\n")

    # Make sure Chrome is running in debug mode
    ensure_chrome_debug()

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_URL)
        # Use the existing context (i.e. Chrome's default profile)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()

        # Fetch first page to get total pages
        print("Reading favorites list...")
        first_page_ids, total_pages = fetch_favorites_page(page, 1)

        if not first_page_ids:
            print("[ERROR] Could not retrieve the favorites list. Possible reasons:")
            print("  1. Not logged in to nhentai.net in Chrome")
            print("  2. The account has no favorites → add some on nhentai.net first")
            print("  3. The page structure changed → please report this issue")
            page.close()
            browser.close()
            return

        # Limit the number of pages scanned (--max-pages)
        scan_pages = min(total_pages, max_pages) if max_pages else total_pages
        if max_pages and max_pages < total_pages:
            print(f"{total_pages} pages of favorites (limiting this run to the first {scan_pages} pages)\n")
        else:
            print(f"{total_pages} pages of favorites\n")

        # Collect all new gallery IDs
        all_new_ids = []
        all_scanned_ids = set()  # full_sync only: used to detect works that were un-favorited
        all_scanned_ordered = []  # full_sync only: IDs in favorites-page order (first = most recently favorited), used to rewrite favorited_at
        consecutive_existing_pages = 0

        for page_num in range(1, scan_pages + 1):
            if page_num == 1:
                page_ids = first_page_ids
            else:
                time.sleep(delay)
                page_ids, _ = fetch_favorites_page(page, page_num)

            if full_sync:
                all_scanned_ids.update(page_ids)
                all_scanned_ordered.extend(page_ids)

            new_on_page = [gid for gid in page_ids if gid not in existing_ids]

            if new_on_page:
                all_new_ids.extend(new_on_page)
                consecutive_existing_pages = 0
            else:
                consecutive_existing_pages += 1

            print(f"  Page {page_num}/{total_pages}: {len(page_ids)} items, {len(new_on_page)} new")

            if not full_sync and consecutive_existing_pages >= 2 and page_num > 2:
                print(f"\n{consecutive_existing_pages} consecutive pages with nothing new; stopping scan (use --full to force a complete scan)")
                break

        # Fetch metadata for each new gallery
        success = 0
        deleted = 0
        errors = 0
        if all_new_ids:
            print(f"\nFound {len(all_new_ids)} new works; fetching details...\n")
            for idx, gid in enumerate(all_new_ids, 1):
                try:
                    time.sleep(delay)
                    api_data = fetch_gallery_metadata(page, gid)

                    if api_data == "DELETED":
                        print(f"  [{idx}/{len(all_new_ids)}] #{gid} [REMOVED] deleted from nhentai, skipping")
                        deleted += 1
                        continue

                    if api_data is None:
                        print(f"  [{idx}/{len(all_new_ids)}] #{gid} [ERROR] failed to fetch data")
                        errors += 1
                        continue

                    doujinshi, tags = parse_gallery_data(api_data)
                    insert_doujinshi(doujinshi, tags)

                    title = doujinshi["title_pretty"] or doujinshi["title_en"] or doujinshi["title_ja"]
                    title_display = title[:50] + "..." if len(title) > 50 else title
                    print(f"  [{idx}/{len(all_new_ids)}] #{gid} {title_display}")
                    success += 1

                except Exception as e:
                    print(f"  [{idx}/{len(all_new_ids)}] #{gid} [EXCEPTION] {e}")
                    errors += 1
        else:
            print("\nNo new works to sync!")

        # Detect and delete un-favorited works (only when --full and all pages were scanned)
        removed_count = 0
        removed_covers = 0
        if full_sync and (not max_pages or max_pages >= total_pages):
            unfavorited = list(existing_ids - all_scanned_ids)
            if unfavorited:
                print(f"\nDetected {len(unfavorited)} un-favorited works; deleting...")
                media_ids = delete_doujinshi_batch(unfavorited)
                removed_count = len(unfavorited)

                cover_cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cover_cache")
                if os.path.isdir(cover_cache_dir):
                    for mid in media_ids:
                        for fname in os.listdir(cover_cache_dir):
                            if fname.startswith(f"{mid}."):
                                os.remove(os.path.join(cover_cache_dir, fname))
                                removed_covers += 1

        # Rewrite favorited_at to match nhentai's favorites order (full --full sync only):
        # page 1 of the favorites list = most recently favorited, so earlier items get a newer
        # favorited_at, keeping a local "favorited time" DESC sort consistent with nhentai's current
        # order (including re-favorited items that move back to the front).
        reordered_count = 0
        if full_sync and (not max_pages or max_pages >= total_pages) and all_scanned_ordered:
            # Deduplicate, keeping the first-seen position (first occurrence = closest to page 1 = most recent)
            seen = set()
            ordered_unique = []
            for gid in all_scanned_ordered:
                if gid not in seen:
                    seen.add(gid)
                    ordered_unique.append(gid)
            reordered_count = update_favorited_order(ordered_unique, base_time=int(time.time()))

        page.close()
        browser.close()

    print(f"\n=== Sync complete ===")
    print(f"Imported:       {success}")
    if deleted:
        print(f"Removed:        {deleted} (deleted on nhentai)")
    if errors:
        print(f"Errors:         {errors}")
    if removed_count:
        cover_note = f"(incl. {removed_covers} cached covers)" if removed_covers else ""
        print(f"Un-favorited:   {removed_count} deleted {cover_note}")
    if reordered_count:
        print(f"Order:          rewrote favorited time for {reordered_count} items to match nhentai's current order")
    print(f"Database total: {len(existing_ids) + success - removed_count}")


def print_help():
    print(
        "nhentai Favorites sync script\n"
        "\n"
        "Usage:\n"
        "  python3 sync.py [options]\n"
        "\n"
        "Options:\n"
        "  (no args)        Incremental sync: scan from page 1, stop after 2 consecutive pages with nothing new\n"
        "  --full           Full sync: scan all pages, rewrite \"favorited time\" to match nhentai's current order,\n"
        "                   and remove works that have been un-favorited on nhentai\n"
        "  --max-pages N    Scan at most the first N pages (for testing); can be combined with --full\n"
        "  -h, --help, --   Show this help and exit\n"
        "\n"
        "Examples:\n"
        "  python3 sync.py                # Incremental sync\n"
        "  python3 sync.py --full         # Full sync (incl. favorited-time ordering)\n"
        "  python3 sync.py --max-pages 5  # Scan only the first 5 pages"
    )


def main():
    args = sys.argv[1:]

    # Note: -h / --help / -- all print the available options
    if "-h" in args or "--help" in args or "--" in args:
        print_help()
        sys.exit(0)

    full_sync = "--full" in args

    max_pages = None
    if "--max-pages" in args:
        idx = args.index("--max-pages")
        try:
            max_pages = int(args[idx + 1])
        except (IndexError, ValueError):
            print("[ERROR] --max-pages must be followed by a number, e.g. python3 sync.py --max-pages 10\n")
            print_help()
            sys.exit(1)

    # Check for unrecognized arguments; print help if any are found
    known = {"--full", "--max-pages", "-h", "--help", "--"}
    unknown = []
    skip_next = False
    for a in args:
        if skip_next:           # skip the value after --max-pages
            skip_next = False
            continue
        if a == "--max-pages":
            skip_next = True
            continue
        if a not in known:
            unknown.append(a)
    if unknown:
        print(f"[ERROR] Unrecognized arguments: {' '.join(unknown)}\n")
        print_help()
        sys.exit(1)

    sync_favorites(full_sync=full_sync, max_pages=max_pages)


if __name__ == "__main__":
    main()
