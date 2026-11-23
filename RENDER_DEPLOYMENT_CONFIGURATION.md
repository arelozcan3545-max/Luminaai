# Lumina AI — Render Dağıtım Yapılandırması

## 1. Temel ayarlar
- Root Directory: proje kökü (`.`)
- Runtime: Python 3.12.10
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/api/v1/health`

## 2. Notlar
- `python main.py` kullanmayın (reload=True, sabit port).
- `worker_entry.py` Cloudflare Workers içindir; Render için kullanılmaz.
- `wrangler.jsonc` Cloudflare içindir; Render için kullanılmaz.
- CORS: üretim origin'i `https://arelozcan3545-max.github.io`.
- Frontend `BACKEND_URL` veya `DEPLOYED_BACKEND_URL` ile backend'e bağlanır.

## GitHub deposundan ilk yayın

1. Proje dosyalarını ve gizli klasör olarak görünen `.github` klasörünü deponun köküne ekleyin. Yerel `.env`, servis hesabı ve model dosyalarını yüklemeyin.
2. Render üzerinde New → Blueprint ile depoyu seçin. Firestore etkin Firebase projenizin hizmet hesabı JSON içeriğini yalnızca Render üzerinde `FIREBASE_SERVICE_ACCOUNT_JSON` gizli değişkenine girin.
3. Kullanacağınız servislerin sunucu anahtarlarını Render ortamına ekleyin. Sohbet için Groq veya Gemini, görsel için Cloudflare Workers AI, Türkçe ses için Google Cloud TTS veya Azure Speech kullanabilirsiniz. Kurucu promosunu taşımak için yerel ortamdaki `LUMINA_FOUNDER_EMAIL` ve `LUMINA_FOUNDER_CODE_SHA256` değerlerini Render ortamına ekleyin. Masaüstündeki modeller sunucuya paketlenmez. Ücretsiz serviste yerel dosyalar yeniden dağıtımda kaybolabilir; kalıcı görseller için kalıcı depolama gerekir.
4. GitHub deposunda Settings → Secrets and variables → Actions → Variables bölümüne `LUMINA_BACKEND_URL` (Render tarafından verilen HTTPS adresi, sonuna /api/v1 eklenebilir) ve `FIREBASE_WEB_CONFIG` (Firebase Console → Proje ayarları → Web uygulamasının JSON yapılandırması) ekleyin. Firebase Authentication authorized domains listesine GitHub Pages alan adını ekleyin.
5. Settings → Pages → Source olarak GitHub Actions seçin. Actions bölümünden Publish Lumina to Pages iş akışını çalıştırın. Sonraki varsayılan dal güncellemeleri otomatik yayınlanır. Başka GitHub hesabında yayın yapıyorsanız o Pages origin adresini Render ALLOWED_ORIGINS listesine ekleyin.
