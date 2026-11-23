# Lumina AI — Render Göç Riskleri

## 1. Veri kaybı riski
- Yerel JSON depo ve medya dosyaları geçici dosya sisteminde.
- Firestore yapılandırılmazsa veri kaybı olur.

## 2. Arka plan işleri
- `_JOBS` bellek içi; yeniden başlatmada kaybolur.
- Kısa ömürlü işler için kabul edilebilir.

## 3. Hız sınırlama
- Bellek içi; yeniden başlatmada sıfırlanır.

## 4. Güvenlik
- `LUMINA_GUEST_SECRET` üretimde zorunlu.
- HTTPS Render tarafından sağlanır.
- CORS sıkı beyaz liste.

## 5. Rollback
- Önceki yedekler mevcut.
- Render deploy geri alınabilir.
