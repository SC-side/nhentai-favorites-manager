#!/bin/bash
# Launch Chrome with a dedicated debug profile for sync.py to connect to
# Usage: bash start_chrome.sh

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# Dedicated debug-only profile so it won't clash with your normal Chrome
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEBUG_PROFILE="$SCRIPT_DIR/chrome-debug-profile"
PORT=9222

# If it's already running in debug mode, just exit
if curl -s "http://localhost:$PORT/json/version" > /dev/null 2>&1; then
    echo "✓ Chrome is already running in debug mode (port $PORT); no need to start it again"
    exit 0
fi

# Kill all Chrome-related processes (including Helper processes)
echo "Closing all Chrome processes..."
pkill -9 -f "Google Chrome" 2>/dev/null
sleep 3
echo "✓ Done"

# Create the debug profile directory (if it doesn't exist)
mkdir -p "$DEBUG_PROFILE"

echo "Starting Chrome (port $PORT, dedicated profile)..."
"$CHROME" \
    --remote-debugging-port=$PORT \
    --user-data-dir="$DEBUG_PROFILE" \
    --no-first-run \
    --no-default-browser-check \
    > /dev/null 2>&1 &

CHROME_PID=$!

# Wait for the debug port to be ready (up to 15 seconds)
for i in $(seq 1 15); do
    sleep 1
    if curl -s "http://localhost:$PORT/json/version" > /dev/null 2>&1; then
        echo "✓ Chrome is ready (port $PORT, PID $CHROME_PID)"
        echo ""

        # Detect first-time use (whether the profile has any login record)
        if [ ! -f "$DEBUG_PROFILE/Default/Cookies" ]; then
            echo "═══════════════════════════════════════════"
            echo "  First-time use: in the Chrome window that just"
            echo "  opened, log in to nhentai.net, then run:"
            echo "  python3 sync.py"
            echo "═══════════════════════════════════════════"
        else
            echo "You can now run:"
            echo "  python3 sync.py"
        fi
        exit 0
    fi
done

echo "[ERROR] Chrome startup timed out; port $PORT not ready"
exit 1
