# Voice Bot - Call Initiator Frontend

A modern web interface for initiating phone calls through your Voice Bot system.

## Features

- 🎨 **Modern UI**: Beautiful, responsive design with smooth animations
- 📱 **Phone Validation**: Real-time phone number validation with international format support
- 🔄 **Real-time Feedback**: Loading states and success/error messages
- 🌐 **Cross-platform**: Works on desktop and mobile browsers
- 🚀 **Easy Setup**: Simple one-click startup

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Make sure your `.env` file contains:

```env
# Twilio Configuration
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=your_twilio_phone_number
WEBHOOK_BASE_URL=your_webhook_url

# Azure OpenAI Configuration
AZURE_OPENAI_API_KEY=your_openai_key
AZURE_OPENAI_ENDPOINT=your_openai_endpoint
OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# Azure Speech Configuration
AZURE_SPEECH_KEY=your_speech_key
AZURE_SPEECH_REGION=your_speech_region
```

### 3. Start the Server

**Option A: Using Python**
```bash
python start_server.py
```

**Option B: Using the batch file (Windows)**
```bash
start_server.bat
```

**Option C: Direct uvicorn**
```bash
cd src
uvicorn api_integration:app --host 0.0.0.0 --port 8000
```

### 4. Access the Frontend

Open your browser and go to: `http://localhost:8000`

## How to Use

1. **Enter Phone Number**: Input the phone number with country code (e.g., +1234567890)
2. **Click "Initiate Call"**: The system will validate the number and initiate the call
3. **Monitor Status**: Success/error messages will appear below the form
4. **Call Management**: The backend handles the call flow using Twilio and Azure services

## Supported Phone Formats

- `+1234567890` (US)
- `+91 98765 43210` (India)
- `+44 20 7946 0958` (UK)
- Any international format with country code

## API Endpoints

- `GET /` - Serves the frontend interface
- `POST /make-call` - Initiates outbound calls
  ```json
  {
    "to_number": "+1234567890"
  }
  ```
- `POST /incoming-call` - Handles incoming call webhooks
- `WebSocket /media-stream` - Handles real-time audio streaming

## Architecture

```
Frontend (HTML/JS) → FastAPI Backend → Twilio API → Phone Call
                                    → Azure OpenAI → AI Response
                                    → Azure Speech → Voice Synthesis
```

## Troubleshooting

### Server Won't Start
- Check if all environment variables are set
- Ensure requirements are installed: `pip install -r requirements.txt`
- Verify Python version compatibility

### Calls Not Connecting
- Verify Twilio credentials in `.env`
- Check if `WEBHOOK_BASE_URL` is accessible from the internet
- Ensure phone numbers include country codes

### Frontend Not Loading
- Make sure `index.html` is in the root directory
- Check browser console for JavaScript errors
- Try refreshing the page

## Development

To run in development mode with auto-reload:

```bash
cd src
uvicorn api_integration:app --host 0.0.0.0 --port 8000 --reload
```

## Security Notes

- In production, update CORS settings to specific origins
- Use HTTPS for webhook URLs
- Secure your environment variables
- Implement rate limiting for the `/make-call` endpoint

## Support

If you encounter issues:
1. Check the server logs for detailed error messages
2. Verify all configuration values in `.env`
3. Test with a simple phone number first
4. Ensure your Twilio account has sufficient balance
