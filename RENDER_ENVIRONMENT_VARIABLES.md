# Lumina AI — Render Ortam Değişkenleri

## Zorunlu
- `LUMINA_ENV=production`
- `LUMINA_GUEST_SECRET` (güçlü, rastgele)
- `ALLOWED_ORIGINS=https://arelozcan3545-max.github.io`

## AI sağlayıcıları
- `GEMINI_API_KEY`
- `GROQ_API_KEY` veya `GROQ_KEY_01..20`
- `GITHUB_TOKEN` / `GITHUB_API_KEY`
- `OPENROUTER_API_KEY`
- `HUGGINGFACE_API_KEY`

## Cloudflare
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`

## Firebase (üretim)
- `FIREBASE_PROJECT_ID`
- `FIREBASE_KEY_PATH` (service account key dosyası yolu)
- `FIREBASE_DATABASE_URL` (gerekirse)

## Frontend
- `DEPLOYED_BACKEND_URL` (frontend config.js veya localStorage)

## Opsiyonel
- `LUMINA_MEDIA_SIGNING_KEY`
- `LUMINA_MAX_UPLOAD_MB`
- `LUMINA_TTS_TIMEOUT_SECS`
- `GOOGLE_TTS_API_KEY` / `AZURE_SPEECH_KEY`

Not: Gerçek değerler bu raporda yer almaz.
