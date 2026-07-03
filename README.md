# OAuth Relay Service

A lightweight, privacy-focused OAuth callback relay for YouTube Analyzer.

## Why This Service?

When setting up YouTube OAuth authentication, Google requires a **fixed callback URL** that must be registered in the Google Cloud Console. This creates a problem for desktop applications:

- **Dynamic ngrok URLs** change every time you restart the tunnel
- **Localhost** can't receive callbacks from remote machines
- Users need to **constantly update** their Google Cloud Console settings

The OAuth Relay Service solves this by providing a **stable, fixed URL** that never changes:

```
https://oauth.yourdomain.com/callback
```

## How It Works

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Local App       │────▶│ Relay Service    │◀────│ Google OAuth    │
│ (YouTube        │     │ (Fixed HTTPS     │     │                 │
│  Analyzer)      │◀────│  URL)            │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                       │
        │  WebSocket/Polling    │  HTTPS callback
        └───────────────────────┘
```

1. **App generates** a unique session ID (UUID)
2. **User is redirected** to Google OAuth with relay callback URL
3. **Google redirects** to relay: `https://oauth.example.com/callback?code=xxx&session={id}`
4. **Relay stores** code in memory (5-minute expiration)
5. **App receives** code via WebSocket (instant) or HTTP polling (fallback)
6. **Relay forgets** session immediately after code retrieval

## Privacy & Security

- **Zero persistence**: No database, no file storage, memory-only sessions
- **Auto-expiration**: Sessions expire after 5 minutes
- **Immediate cleanup**: Sessions deleted after code retrieval
- **No tokens stored**: Only the temporary authorization code passes through
- **Open source**: Full transparency - audit the code yourself

## Deployment

### Docker (Recommended)

```bash
docker build -t oauth-relay .
docker run -p 8000:8000 oauth-relay
```

### Docker Compose

```bash
docker-compose up -d
```

### Coolify

1. Create a new service from this repository
2. Set domain to `oauth.yourdomain.com`
3. Enable HTTPS (automatic Let's Encrypt)
4. Deploy

### Direct Python

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Service info |
| `/health` | GET | Health check for monitoring |
| `/callback` | GET | OAuth callback (receives code from Google) |
| `/poll/{session_id}` | GET | HTTP polling for code retrieval |
| `/ws/{session_id}` | WebSocket | Real-time code transmission |
| `/docs` | GET | Interactive API documentation |

## Configuration for YouTube Analyzer

1. Deploy this service to a public URL (e.g., `https://oauth.yourdomain.com`)
2. Add to `.env` in YouTube Analyzer:
   ```env
   OAUTH_RELAY_URL=https://oauth.yourdomain.com
   OAUTH_RELAY_ENABLED=true
   ```
3. In Google Cloud Console, add authorized redirect URI:
   ```
   https://oauth.yourdomain.com/callback
   ```

## License

MIT License - see LICENSE file.
