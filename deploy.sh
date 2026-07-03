#!/bin/bash

set -e  # exit on error

PROJECT_ROOT="/home/ubuntu/swara"

echo "🚀 Starting Swara deployment..."

cd "$PROJECT_ROOT"

echo "📥 Pulling latest code..."
git pull origin main

echo "📦 Installing backend dependencies..."
source src/venv/bin/activate
pip install -r src/requirements.txt
pip install -r VAD/requirements.txt || echo "⚠️ VAD deps install failed (non-fatal — backend falls back to energy-based VAD)"
deactivate

echo "🔁 Restarting backend service..."
sudo systemctl restart swara-voicebot.service

echo "🧪 Checking service status..."
sudo systemctl is-active --quiet swara-voicebot.service && echo "✅ Backend OK" || echo "❌ Backend FAILED"

echo "🏗️ Building frontend..."
cd frontend
npm install --silent
npm run build
cd ..

echo "🔄 Reloading Nginx..."
sudo nginx -t && sudo systemctl reload nginx

echo "✅ Deployment complete!"
