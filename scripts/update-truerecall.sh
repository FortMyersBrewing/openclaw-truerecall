#!/bin/bash
# ============================================================================
# TrueRecall Update Script
# Run this on any machine with TrueRecall installed to:
#   1. Pull latest code
#   2. Stop services
#   3. Prune junk memories from Qdrant
#   4. Restart services with new filters
#
# Usage: ./update-truerecall.sh [--dry-run]
# ============================================================================

set -e

DRY_RUN=false
if [ "$1" = "--dry-run" ]; then
  DRY_RUN=true
  echo "🧪 DRY RUN MODE — no changes will be made"
fi

REPO_DIR="$HOME/projects/openclaw-truerecall"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
COLLECTION="${QDRANT_COLLECTION:-memories_tr}"

echo "============================================"
echo "  TrueRecall Update — $(date)"
echo "============================================"
echo ""

# Step 1: Pull latest code
echo "📥 Step 1: Pulling latest code..."
cd "$REPO_DIR"
git pull origin main
echo "  ✅ Code updated"
echo ""

# Step 2: Stop services
echo "⏸️  Step 2: Stopping services..."
launchctl unload ~/Library/LaunchAgents/com.openclaw.truerecall-gems.plist 2>/dev/null && echo "  Gems stopped" || echo "  Gems not running"
launchctl unload ~/Library/LaunchAgents/com.openclaw.truerecall-watcher.plist 2>/dev/null && echo "  Watcher stopped" || echo "  Watcher not running"
echo ""

# Step 3: Prune junk memories
echo "🧹 Step 3: Pruning junk memories..."
export DRY_RUN
python3 << 'PYPRUNE'
import json, urllib.request, os

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = os.getenv("QDRANT_COLLECTION", "memories_tr")
DRY_RUN = os.getenv("DRY_RUN", "false") == "true"

url_scroll = f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll"
url_delete = f"{QDRANT_URL}/collections/{COLLECTION}/points/delete"
url_count = f"{QDRANT_URL}/collections/{COLLECTION}/points/count"

try:
    req = urllib.request.Request(url_count, data=b'{"exact":true}', headers={"Content-Type": "application/json"}, method="POST")
    initial = json.loads(urllib.request.urlopen(req, timeout=10).read())["result"]["count"]
    print(f"  Current memory count: {initial}")
except:
    print("  ❌ Cannot reach Qdrant. Is it running?")
    exit(1)

to_delete = []
offset = None
while True:
    body = {"limit": 100, "with_payload": True}
    if offset:
        body["offset"] = offset
    req = urllib.request.Request(url_scroll, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    data = json.loads(urllib.request.urlopen(req, timeout=10).read())
    points = data.get("result", {}).get("points", [])
    if not points:
        break
    for pt in points:
        text = (pt.get("payload", {}).get("text", "") or pt.get("payload", {}).get("content", "")).strip()
        words = len(text.split())
        if words < 5 or len(text) < 20:
            to_delete.append(pt["id"])
        elif text.startswith("[media attached:") and "To send an image back" in text:
            to_delete.append(pt["id"])
        elif text.startswith("[Slack file:") and len(text) < 80:
            to_delete.append(pt["id"])
    offset = data.get("result", {}).get("next_page_offset")
    if not offset:
        break

print(f"  Found {len(to_delete)} junk memories")
if DRY_RUN:
    print(f"  🧪 Dry run — skipping delete")
elif to_delete:
    deleted = 0
    for i in range(0, len(to_delete), 500):
        batch = to_delete[i:i+500]
        req = urllib.request.Request(url_delete, data=json.dumps({"points": batch}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        if json.loads(urllib.request.urlopen(req, timeout=30).read()).get("status") == "ok":
            deleted += len(batch)
    req = urllib.request.Request(url_count, data=b'{"exact":true}', headers={"Content-Type": "application/json"}, method="POST")
    final = json.loads(urllib.request.urlopen(req, timeout=10).read())["result"]["count"]
    print(f"  Deleted: {deleted} | Remaining: {final}")
else:
    print(f"  Nothing to prune! 🎉")
PYPRUNE
echo ""

# Step 4: Rebuild MCP server if present
if [ -d "$REPO_DIR/mcp-server" ]; then
  echo "🔨 Step 4: Rebuilding MCP server..."
  cd "$REPO_DIR/mcp-server"
  npm install --silent 2>&1 | tail -1
  npm run build 2>&1 | tail -1
  if launchctl list 2>/dev/null | grep -q "truerecall-mcp"; then
    launchctl unload ~/Library/LaunchAgents/com.fmbrew.truerecall-mcp.plist 2>/dev/null
    sleep 1
    launchctl load ~/Library/LaunchAgents/com.fmbrew.truerecall-mcp.plist 2>/dev/null
    echo "  ✅ MCP server rebuilt and restarted"
  else
    echo "  ✅ MCP server rebuilt (no launchd service)"
  fi
  echo ""
fi

# Step 5: Restart services
echo "▶️  Step 5: Restarting services..."
launchctl load ~/Library/LaunchAgents/com.openclaw.truerecall-watcher.plist 2>/dev/null && echo "  ✅ Watcher started" || echo "  ⚠️ Watcher plist not found"
launchctl load ~/Library/LaunchAgents/com.openclaw.truerecall-gems.plist 2>/dev/null && echo "  ✅ Gems started" || echo "  ⚠️ Gems plist not found"
echo ""

echo "============================================"
echo "  ✅ TrueRecall update complete!"
echo "============================================"
echo "  • Watcher: skips media boilerplate, < 5 word messages"
echo "  • Gems: min 50 chars + 5 words, stricter LLM prompt"
echo "  • Pruned junk from Qdrant"
