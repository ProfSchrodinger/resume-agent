#!/bin/bash
# Resume Agent — quick start script
# Usage: ./run.sh

set -e

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Resume Agent"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check RESUME_REPO_PATH
if [ -z "$RESUME_REPO_PATH" ]; then
  echo ""
  echo "  RESUME_REPO_PATH is not set."
  echo "  Where is your resume-latex repo? (e.g. ~/Documents/resume-latex)"
  read -p "  Path: " REPO_PATH
  export RESUME_REPO_PATH="${REPO_PATH/#\~/$HOME}"
  echo ""
fi

# Check ANTHROPIC_API_KEY
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo ""
  echo "  ANTHROPIC_API_KEY is not set."
  echo "  You can also enter it in the browser UI."
  echo "  Press enter to skip, or paste your key:"
  read -p "  API Key: " API_KEY
  if [ -n "$API_KEY" ]; then
    export ANTHROPIC_API_KEY="$API_KEY"
  fi
fi

echo ""
echo "  Repo:    $RESUME_REPO_PATH"
echo "  API Key: ${ANTHROPIC_API_KEY:+set ✓}"
echo ""

# Install deps if needed
if ! python3 -c "import flask, anthropic" 2>/dev/null; then
  echo "  Installing dependencies..."
  pip3 install -r requirements.txt -q
fi

echo "  Starting server → http://localhost:5000"
echo "  Press Ctrl+C to stop."
echo ""

python3 app.py
