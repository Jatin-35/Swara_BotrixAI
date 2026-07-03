#!/bin/bash

set -e  # exit on error

PROJECT_ROOT="/home/ubuntu/swara"

echo "🚀 Starting Swara deployment..."

cd "$PROJECT_ROOT"

echo "📥 Pulling latest code..."
git pull origin main

echo "📦 Installing backend dependencies..."
source venv/bin/activate
pip install -r src/requirements.txt
pip install -r VAD/requirements.txt
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
