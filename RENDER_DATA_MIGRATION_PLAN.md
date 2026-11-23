# Lumina AI — Veri Göç Planı

## 1. Mevcut veri
- Yerel JSON (`lumina_memory.json`): kullanıcı profili, kota, sohbet geçmişi.
- Firestore (opsiyonel): profil aynası.
- `media/`: üretilen görseller.

## 2. Göç adımları
1. Firestore'u etkinleştir (service account key).
2. `sync_profiles_from_firestore()` ile mevcut profilleri Firestore'a taşı.
3. Medya dosyalarını harici depolamaya taşı (isteğe bağlı).
4. Yerel JSON'u yedek olarak sakla.
5. Üretimde Firestore'u zorunlu tut.

## 3. Güvenlik
- Mevcut verileri silme veya üzerine yazma.
- Göç öncesi yedek al.
- Geri dönüş planı hazırla.

## 4. Notlar
- Göç bu aşamada uygulanmadı; yalnızca planlandı.
- Kullanıcı onayı ve kimlik bilgileri gerekli.
