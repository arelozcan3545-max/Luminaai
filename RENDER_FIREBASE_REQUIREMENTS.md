# Lumina AI — Firebase Gereksinimleri

## 1. Firebase Web (frontend)
- `config.js` içinde `FIREBASE_CONFIG`.
- Web appId doğrulanmalı (şu an Android appId kullanılıyor).
- Authorized domains: `localhost`, `127.0.0.1`, GitHub Pages domain.

## 2. Firebase Authentication
- Google OAuth ve e-posta/şifre.
- Frontend Firebase SDK ile token alır.
- Backend `verify_token` ile doğrular.

## 3. Firebase Admin SDK (backend)
- `serviceAccountKey.json` veya `FIREBASE_KEY_PATH`.
- Firestore istemcisi oluşturur.
- Üretimde zorunlu (kalıcı veri için).

## 4. Firestore
- `user_quota_usage/{uid}` dokümanları.
- Profil ve kota verileri.
- Transaction ile atomik güncelleme.

## 5. Firebase Storage
- Şu an kullanılmıyor; medya yerel `media/` klasöründe.
- İsteğe bağlı: görselleri Firebase Storage'a taşı.
