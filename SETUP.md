# TrueRecall Setup Guide

## Overview
Vector-based memory system for OpenClaw agents. Embeds every conversation turn into Qdrant (vector DB) via Ollama (local embeddings). Enables cross-session semantic search over entire conversation history.

**Source repo:** https://gitlab.com/mdkrush/openclaw-true-recall-base
**Local clone:** ~/projects/openclaw-true-recall-base

## Architecture
```
Session JSONL files → Watcher daemon → Ollama (embed) → Qdrant (store)
                                         ↑                    ↑
                            snowflake-arctic-embed2      memories_tr collection
                            (1024 dimensions)            (cosine similarity)
```

## Prerequisites
- macOS (Apple Silicon) or Linux
- Homebrew (macOS)
- Python 3.x

## Step 1: Install Ollama
```bash
brew install ollama
brew services start ollama
ollama pull snowflake-arctic-embed2
```
- Runs as brew service (auto-start on boot)
- Embedding model: `snowflake-arctic-embed2` — 1024 dimensions (NOT 768 as README claims)
- Endpoint: http://localhost:11434

## Step 2: Install Docker Desktop
```bash
# Requires sudo for /usr/local/cli-plugins and /usr/local/bin symlinks
sudo mkdir -p /usr/local/cli-plugins
brew install --cask docker
# Open Docker Desktop, accept terms, recommended settings is fine
# Sign-in is optional (not needed for public images)
open -a Docker
```

## Step 3: Run Qdrant
```bash
docker run -d --name qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage \
  --restart unless-stopped \
  qdrant/qdrant
```
- REST API: http://localhost:6333
- gRPC: localhost:6334
- Data persists in Docker volume `qdrant_storage`
- Auto-restarts with Docker

## Step 4: Create Collection
```bash
curl -s -X PUT http://localhost:6333/collections/memories_tr \
  -H "Content-Type: application/json" \
  -d '{"vectors": {"size": 1024, "distance": "Cosine"}}'
```
**IMPORTANT:** Use 1024 dimensions, not 768. The snowflake-arctic-embed2 model outputs 1024-dim vectors.

## Step 5: Clone & Setup Watcher
```bash
cd ~/projects
git clone https://gitlab.com/mdkrush/openclaw-true-recall-base.git
cd openclaw-true-recall-base
python3 -m venv venv
./venv/bin/pip install requests
```

### Patch: Make SESSIONS_DIR configurable
In `watcher/realtime_qdrant_watcher.py`, change:
```python
SESSIONS_DIR = Path("/root/.openclaw/agents/main/sessions")
```
to:
```python
SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "/root/.openclaw/agents/main/sessions"))
```

### Create launcher script
```bash
cat > ~/projects/openclaw-true-recall-base/run-watcher.sh << 'EOF'
#!/bin/bash
cd /Users/YOUR_USER/projects/openclaw-true-recall-base
source venv/bin/activate
export QDRANT_URL="http://localhost:6333"
export OLLAMA_URL="http://localhost:11434"
export USER_ID="YOUR_AGENT_NAME"
export SESSIONS_DIR="/Users/YOUR_USER/.openclaw/agents/main/sessions"
exec python -u watcher/realtime_qdrant_watcher.py "$@"
EOF
chmod +x ~/projects/openclaw-true-recall-base/run-watcher.sh
```

## Step 6: launchd Service (macOS)
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openclaw.truerecall-watcher</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/Users/YOUR_USER/projects/openclaw-true-recall-base/run-watcher.sh</string>
        <string>--daemon</string>
        <string>--user-id</string>
        <string>YOUR_AGENT_NAME</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/truerecall-watcher.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/truerecall-watcher.err</string>
</dict>
</plist>
```

Save to: `~/Library/LaunchAgents/com.openclaw.truerecall-watcher.plist`

```bash
launchctl load ~/Library/LaunchAgents/com.openclaw.truerecall-watcher.plist
# Verify:
launchctl list | grep truerecall
cat /tmp/truerecall-watcher.log
```

## Step 7: Backfill Historical Sessions
Run the backfill script (see below). This processes all existing JSONL session files and embeds them into Qdrant. Takes ~30-60 min for ~88 sessions on Apple Silicon.

The backfill script is inline in the exec command — see memory/2026-02-28.md for the full script. Key points:
- Deterministic point IDs from `sha256(session_name:turn:N)` — idempotent, safe to re-run
- Skips system/tool messages, only stores user + assistant turns
- Cleans markdown formatting, metadata blocks, thinking tags
- Truncates content to 2000 chars per turn
- Tags each point with `source: "backfill"` vs `source: "true-recall-base"` for live capture

## Verification
```bash
# Check Qdrant collection stats
curl -s http://localhost:6333/collections/memories_tr | python3 -m json.tool

# Test semantic search
python3 -c "
import urllib.request, json
query = 'YOUR SEARCH QUERY'
data = json.dumps({'model': 'snowflake-arctic-embed2', 'prompt': query}).encode()
req = urllib.request.Request('http://localhost:11434/api/embeddings', data=data, headers={'Content-Type': 'application/json'})
embedding = json.loads(urllib.request.urlopen(req).read())['embedding']
search = json.dumps({'vector': embedding, 'limit': 5, 'with_payload': True}).encode()
req2 = urllib.request.Request('http://localhost:6333/collections/memories_tr/points/search', data=search, headers={'Content-Type': 'application/json'})
results = json.loads(urllib.request.urlopen(req2).read())['result']
for r in results:
    print(f'score={r[\"score\"]:.4f} [{r[\"payload\"][\"role\"]}]: {r[\"payload\"][\"content\"][:120]}')
"
```

## Ports Summary
| Service | Port | Protocol |
|---------|------|----------|
| Qdrant REST | 6333 | HTTP |
| Qdrant gRPC | 6334 | gRPC |
| Ollama | 11434 | HTTP |

## Gotchas & Lessons
1. **Dimensions:** snowflake-arctic-embed2 = 1024 dims, NOT 768 as TrueRecall README states
2. **macOS pip:** System Python blocks `pip install`. Must use a venv.
3. **launchd env vars:** Don't rely on plist EnvironmentVariables — they can be overridden. Bake env vars into the launcher shell script instead.
4. **Python stdout buffering:** Use `python -u` flag for unbuffered output in launchd, otherwise logs appear empty.
5. **--once mode bug:** The watcher's `--once` mode still runs `watch_session()` which loops forever. Use `--daemon` for real use.
6. **Docker Desktop sudo:** Needs sudo for `/usr/local/cli-plugins` and `/usr/local/bin/hub-tool` symlinks during install.
7. **Docker auto-start:** Docker Desktop starts on login by default. Qdrant container has `--restart unless-stopped` so it comes back with Docker.

## TODO
- [ ] Expand watcher to cover ALL agent sessions (not just main)
- [ ] Build search skill/hook for querying Qdrant during any conversation
- [ ] Backfill non-main agent sessions
- [ ] Install Gems addon (auto-curate important memories)
- [ ] Install Blocks addon (topic clustering)
- [ ] Hopster setup (Windows — will need systemd or Windows service equivalent)
- [ ] Quinn setup (same as AVA — macOS)

## Adaptation for Hopster (Windows)
- Docker Desktop for Windows (WSL2 backend)
- Ollama for Windows (native installer from ollama.com)
- Qdrant same Docker command
- Watcher: use Task Scheduler or nssm instead of launchd
- Sessions path: adjust to Windows OpenClaw path

## Adaptation for Quinn (macOS)
- Same steps as AVA
- Change USER_ID to "quinn"
- Change SESSIONS_DIR to Quinn's sessions path
- Same Qdrant collection (shared) OR separate collection per agent
