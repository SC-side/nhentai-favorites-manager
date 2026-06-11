import json
import os
import platform
import shutil

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "cookies": {},
    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "browser_path": "",
    "port": 5001,
    "request_delay": 1.5,
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        for key, val in DEFAULT_CONFIG.items():
            config.setdefault(key, val)
        return config
    return dict(DEFAULT_CONFIG)


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def parse_cookie_string(cookie_str):
    """Parse a raw Cookie header string like 'name1=value1; name2=value2' into a dict."""
    cookies = {}
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if "=" in pair:
            name, value = pair.split("=", 1)
            cookies[name.strip()] = value.strip()
    return cookies


def prompt_cookies():
    """Interactive cookie input for first-time setup."""
    print("\n=== nhentai Cookie setup ===")
    print("Log in to nhentai.net first, then get your cookies in either of these ways:\n")
    print("[Method A] Copy the full Cookie string (recommended):")
    print("  1. On nhentai.net, press F12 to open DevTools")
    print("  2. Switch to the Network tab and refresh the page")
    print("  3. Click any request → Headers → Request Headers")
    print("  4. Find the Cookie: field and copy the entire value")
    print("  5. Paste it below\n")
    print("[Method B] Enter cookies one by one (leave blank to skip)\n")

    raw = input("Paste the full Cookie string (or just press Enter to enter them one by one): ").strip()

    if raw:
        # Strip a possible "Cookie: " prefix
        if raw.lower().startswith("cookie:"):
            raw = raw[7:].strip()
        cookies = parse_cookie_string(raw)
        if cookies:
            print(f"\nParsed {len(cookies)} cookies: {', '.join(cookies.keys())}")
            return cookies
        else:
            print("Could not parse; falling back to one-by-one entry...\n")

    # Fallback: enter one by one
    cookies = {}

    cf_clearance = input("cf_clearance (Cloudflare cookie): ").strip()
    if cf_clearance:
        cookies["cf_clearance"] = cf_clearance

    access_token = input("access_token (login token): ").strip()
    if access_token:
        cookies["access_token"] = access_token

    print("\nEnter any other cookies (format: name=value); blank line to finish:")
    while True:
        extra = input("> ").strip()
        if not extra:
            break
        if "=" in extra:
            name, value = extra.split("=", 1)
            cookies[name.strip()] = value.strip()

    return cookies


def get_browser_command():
    """Auto-detect browser and return (executable_path, incognito_flag).
    Returns (None, None) if detection fails."""
    system = platform.system()

    # Check config for manual override
    config = load_config()
    manual_path = config.get("browser_path", "")
    if manual_path and os.path.exists(manual_path):
        lower = manual_path.lower()
        if "firefox" in lower:
            return (manual_path, "--private-window")
        return (manual_path, "--incognito")

    if system == "Darwin":  # macOS
        chrome_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
        firefox_paths = [
            "/Applications/Firefox.app/Contents/MacOS/firefox",
            os.path.expanduser("~/Applications/Firefox.app/Contents/MacOS/firefox"),
        ]
        for p in chrome_paths:
            if os.path.exists(p):
                return (p, "--incognito")
        for p in firefox_paths:
            if os.path.exists(p):
                return (p, "--private-window")

        # Fallback: use 'open' command with Chrome bundle
        if os.path.exists("/Applications/Google Chrome.app"):
            return ("macos-chrome", None)
        if os.path.exists("/Applications/Firefox.app"):
            return ("macos-firefox", None)

    elif system == "Windows":
        chrome_candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        firefox_candidates = [
            os.path.expandvars(r"%ProgramFiles%\Mozilla Firefox\firefox.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"),
        ]
        for p in chrome_candidates:
            if os.path.exists(p):
                return (p, "--incognito")
        for p in firefox_candidates:
            if os.path.exists(p):
                return (p, "--private-window")

    else:  # Linux
        for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]:
            path = shutil.which(name)
            if path:
                return (path, "--incognito")
        for name in ["firefox", "firefox-esr"]:
            path = shutil.which(name)
            if path:
                return (path, "--private-window")

    return (None, None)
