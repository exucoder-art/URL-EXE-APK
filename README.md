# EXU · URL-to-App Converter

**Turn any public website into a downloadable Android APK or Windows EXE.**

Premium dark liquid-glass UI · Flask backend · Server-side automated build workers · Secure URL validation · Live build status & downloads.

---

## Features

| Feature | Description |
|---------|-------------|
| **URL → Native App** | Converts any public HTTP/HTTPS URL into Android APK and/or Windows EXE |
| **Secure validation** | Blocks private/localhost IPs, dangerous schemes, oversized payloads |
| **App customization** | Name, package ID, theme color, custom icon |
| **Server-side workers** | Background build threads with live progress + log streaming |
| **Premium UI** | Dark liquid-glass design with ambient orbs, glass cards, smooth animations |
| **Rate limiting** | Per-IP hourly build limit |
| **Metadata fetch** | Auto-pulls site title, description & favicon |

> **Note:** The included build workers generate realistic *demo* artifacts (valid ZIP-based APK structure + PE-stub EXE).  
> For production you would swap the simulation steps in `workers/builder.py` with real toolchains (Capacitor / TWA / Bubblewrap for Android, Electron-builder or Tauri for Windows).

---

## Quick Start

### 1. Prerequisites

- Python 3.10+
- `pip`

### 2. Install

```bash
cd exu-url-to-app
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # optional – edit secrets
```

### 3. Run

```bash
python app.py
```

Open **http://127.0.0.1:5000**

---

## Project Structure

```
exu-url-to-app/
├── app.py                  # Flask entry point + API routes
├── config.py               # Configuration
├── requirements.txt
├── .env.example
├── backend/
│   ├── validators.py       # Secure URL & input validation + metadata
│   └── build_manager.py    # Job store, rate limits, persistence
├── workers/
│   └── builder.py          # Background APK / EXE build workers
├── templates/
│   └── index.html          # Single-page UI
├── static/
│   ├── css/style.css       # Liquid-glass design system
│   └── js/app.js           # Frontend logic (validate, poll, download)
├── builds/                 # Generated artifacts (apk/, exe/)
├── uploads/                # User-uploaded icons
└── README.md
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/` | Frontend |
| `GET`  | `/api/health` | Health check |
| `POST` | `/api/validate-url` | Validate URL + fetch metadata |
| `POST` | `/api/build` | Queue a new build (multipart or JSON) |
| `GET`  | `/api/status/<job_id>` | Poll build progress & logs |
| `GET`  | `/api/download/<job_id>/<target>` | Download `apk` or `exe` |
| `GET`  | `/api/recent` | Recent jobs (sanitized) |

### Example – start a build

```bash
curl -X POST http://127.0.0.1:5000/api/build \
  -F "url=https://example.com" \
  -F "app_name=Example App" \
  -F "package_name=com.example.app" \
  -F "theme_color=#6366f1" \
  -F "targets=apk,exe"
```

---

## Security Notes

- Only `http` / `https` public URLs are accepted.
- Private, loopback and link-local address ranges are blocked.
- Icon uploads are verified with Pillow and re-encoded as PNG.
- Build artifacts are path-checked before serving.
- Rate limit: 5 builds per IP per hour (configurable).
- No arbitrary code execution – the demo builders only write static files.

---

## Production Hints

1. Set a strong `FLASK_SECRET_KEY`.
2. Put the app behind Gunicorn + Nginx / Caddy.
3. Replace the simulated builders with real toolchains and signing keys.
4. Optionally enable Celery + Redis (hooks are prepared in `config.py`).
5. Store jobs in a proper database instead of JSON files for multi-instance deployments.

---

## License

MIT – use freely. Real app-store distribution still requires your own signing certificates and compliance with platform policies.
