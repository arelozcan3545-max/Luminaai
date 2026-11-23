# Lumina AI — Render Depolama Mimarisi

## 1. Mevcut depolama
- Yerel JSON (`lumina_memory.json`): kullanıcı profili, kota, sohbet geçmişi.
- Firestore (opsiyonel): profil aynası.
- `media/`: üretilen görseller.
- Bellek içi: arka plan işleri, hız sınırlama.

## 2. Seçenekler
- **Firebase Firestore**: kalıcı, ölçeklenebilir, mevcut ayna mantığı ile uyumlu. Önerilen.
- **Render persistent disk**: basit ama tek instance; ölçeklenebilir değil.
- **Harici nesne depolama (R2/S3)**: medya için önerilen.
- **Yerel JSON**: yalnızca geliştirme.

## 3. Öneri
- Üretimde Firestore'u zorunlu tut.
- Medya için harici nesne depolama veya Render disk kullan.
- Yerel JSON'u geliştirme için sakla.
