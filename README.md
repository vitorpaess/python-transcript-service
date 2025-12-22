# YouTube Transcript Microservice

A Python microservice using `youtube-transcript-api` to fetch YouTube captions.

## Local Development

```bash
cd python-transcript-service
pip install -r requirements.txt
python main.py
```

The service runs on `http://localhost:8080`.

## API Endpoints

### Health Check
```
GET /health
```

### Fetch Transcript
```
POST /transcript
Content-Type: application/json

{
  "video_id": "dQw4w9WgXcQ",
  "preferred_languages": ["en", "en-US"]
}
```

Response:
```json
{
  "success": true,
  "text": "Full transcript text here...",
  "language": "en",
  "is_auto_generated": false
}
```

## Deploy to Fly.io

```bash
cd python-transcript-service
fly launch
fly deploy
```

## Deploy to Render

1. Create a new Web Service
2. Connect your repo
3. Set root directory to `python-transcript-service`
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

## Deploy to Railway

1. Create new project from GitHub
2. Set root directory to `python-transcript-service`
3. Railway auto-detects Python and deploys

## Environment Variables

After deploying, set `TRANSCRIPT_SERVICE_URL` in Lovable Cloud secrets to your service URL (e.g., `https://your-service.fly.dev`).

## Why This Might Fail in Production

The `youtube-transcript-api` library scrapes YouTube directly (no official API). Issues include:

- **IP blocking**: Cloud IPs may be blocked by YouTube
- **Rate limiting**: Too many requests trigger captchas
- **Region/consent**: Some regions require cookie consent
- **Bot detection**: YouTube may detect non-browser traffic

**Mitigations:**
- Use residential proxies
- Add request delays
- Rotate user agents
- Consider a proxy service like ScraperAPI
