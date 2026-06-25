#!/bin/bash
# start.sh — starts ProductValidation OS (API + Dashboard, single process)
# Usage: ./start.sh

set -e
cd "$(dirname "$0")"

echo ""
echo "============================================"
echo "   ProductValidation OS"
echo "============================================"
echo ""

if [ ! -d "venv" ]; then
  echo "venv not found. Run this first:"
  echo "  python3 -m venv venv"
  echo "  source venv/bin/activate"
  echo "  pip install -r requirements.txt --break-system-packages"
  echo "  playwright install chromium"
  exit 1
fi

source venv/bin/activate

if [ ! -f ".env" ]; then
  echo ".env file not found. Create it with: GEMINI_API_KEY=your_key"
  exit 1
fi

echo "Starting server on http://localhost:8000"
echo "  - Dashboard:  http://localhost:8000"
echo "  - API health: http://localhost:8000/health"
echo ""
echo "To expose this to the internet (e.g. for a remote demo), in another"
echo "terminal run:  ngrok http 8000"
echo ""
echo "Press Ctrl+C to stop"
echo ""

cd api && exec python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload