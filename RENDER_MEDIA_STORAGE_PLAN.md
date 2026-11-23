# Lumina AI — Medya Depolama Planı

## 1. Mevcut durum
- Üretilen görseller `media/` klasörüne kaydediliyor.
- İmzalı, süreli URL ile sunuluyor.
- Dosya adı `lumina_{timestamp}_{random}.{ext}`.

## 2. Render riski
- Render geçici dosya sisteminde medya kaybolur.

## 3. Seçenekler
- **Render persistent disk**: basit, tek instance.
- **Cloudflare R2 / AWS S3**: ölçeklenebilir, harici.
- **Firebase Storage**: Firebase ile uyumlu.

## 4. Öneri
- Kısa vadede Render persistent disk kullan.
- Uzun vadede harici nesne depolama (R2/S3) değerlendir.
- Mevcut URL yapısını koru; yalnızca depolama backend'ini değiştir.
- Mevcut görselleri silme veya taşıma; yeni görseller yeni backend'e yaz.
