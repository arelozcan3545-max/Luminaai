# ============================================================
# LUMINA AI - CANLI GÖRSEL TEST MATRİSİ (20 kategori x 2 = 40)
# ------------------------------------------------------------
# Bu modül GERÇEK görsel üretir. Sağlayıcı anahtarı yoksa hiçbir
# istek atılmaz ve sonuç dürüstçe BLOCKED raporlanır.
#
# Kullanım (PowerShell):
#   $env:LUMINA_IMAGE_PROVIDER_ORDER = "cloudflare"
#   & ".\.venv\Scripts\python.exe" live_image_matrix.py
#
# İsteğe bağlı:
#   $env:LUMINA_IMAGE_ARTIFACT_DIR = "C:\...\lumina_gorsel_testleri"
#
# Kurallar:
#   * Sır değerleri yazdırılmaz, diske yazılmaz, hata metnine sızmaz.
#   * Pollinations bu koşucuda HER ZAMAN kapalıdır.
#   * Görsel KALİTESİ otomatik olarak değerlendirilmez; her vaka
#     "quality_review": "pending" olarak işaretlenir ve insan
#     incelemesi bekler.
# ============================================================

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:  # .env varsa oku (repoya girmez; .gitignore'da)
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001 - dotenv opsiyonel
    pass

import image_engine

# ------------------------------------------------------------
# 20 KATEGORİ x 2 İSTEM = 40 GERÇEK GÖRSEL
# ------------------------------------------------------------
# Kategoriler denetim talimatındaki 20 başlıkla birebir eşleşir.
# Tüm istemler Türkçedir: ürün Türkçe kullanılıyor ve sağlayıcının
# Türkçe istem sadakati gerçekten ölçülmek isteniyor.
CATEGORIES: List[Dict[str, object]] = [
    {
        "id": "nature",
        "label": "Doğa",
        "prompts": [
            "orman içinde akan dere, yosunlu kayalar, sabah ışığı",
            "bahar çiçekleriyle kaplı çayır, kelebekler",
        ],
    },
    {
        "id": "landscapes",
        "label": "Manzaralar",
        "prompts": [
            "kapadokya'da gün doğumu, sıcak hava balonları",
            "karadeniz dağları, sisli yeşil vadiler",
        ],
    },
    {
        "id": "architecture",
        "label": "Mimari",
        "prompts": [
            "selçuklu camii, taş işçiliği, mavi gökyüzü",
            "modern cam ofis binası, gün batımı yansıması",
        ],
    },
    {
        "id": "cities",
        "label": "Şehirler",
        "prompts": [
            "istanbul'da akşam saatinde kalabalık sokak, tramvay",
            "gece şehir silueti, ışıklı gökdelenler",
        ],
    },
    {
        "id": "animals",
        "label": "Hayvanlar",
        "prompts": [
            "tekir kedi, pencere kenarında güneşleniyor",
            "golden retriever köpek, parkta koşuyor",
        ],
    },
    {
        "id": "technology",
        "label": "Teknoloji",
        "prompts": [
            "robot kol, modern fabrika hattı",
            "sunucu odası, mavi LED ışıklar",
        ],
    },
    {
        "id": "space",
        "label": "Uzay",
        "prompts": [
            "uzay istasyonu, dünya yörüngesinde",
            "satürn halkaları, yıldızlı arka plan",
        ],
    },
    {
        "id": "education",
        "label": "Eğitim",
        "prompts": [
            "aydınlık sınıf, öğrenciler ders çalışıyor",
            "kütüphane rafları, açık kitaplar",
        ],
    },
    {
        "id": "science",
        "label": "Bilim",
        "prompts": [
            "mikroskop altında hücre yapısı, bilimsel illüstrasyon",
            "laboratuvarda deney düzeneği, cam beherler",
        ],
    },
    {
        "id": "food",
        "label": "Yemek",
        "prompts": [
            "geleneksel Türk kahvaltısı tabağı, üstten çekim",
            "fırından yeni çıkmış ekmek, odun ateşi",
        ],
    },
    {
        "id": "vehicles",
        "label": "Araçlar",
        "prompts": [
            "kırmızı klasik otomobil, sahil yolu",
            "yük treni, dağ geçidi, uzun raylar",
        ],
    },
    {
        "id": "fantasy_environments",
        "label": "Fantastik ortamlar",
        "prompts": [
            "dev mantarlarla kaplı büyülü orman",
            "yüzen adalar, şelaleler, fantastik gökyüzü",
        ],
    },
    {
        "id": "product_concepts",
        "label": "Ürün konseptleri",
        "prompts": [
            "el yapımı seramik kupa, ahşap masa",
            "minimalist kulaklık ürün fotoğrafı, stüdyo",
        ],
    },
    {
        "id": "illustrations",
        "label": "İllüstrasyonlar",
        "prompts": [
            "suluboya çocuk kitabı illüstrasyonu, parkta oynayan çocuklar",
            "çizgi film tarzı sevimli tilki, ormanda",
        ],
    },
    {
        "id": "abstract_art",
        "label": "Soyut sanat",
        "prompts": [
            "soyut geometrik kompozisyon, sıcak renkler",
            "akışkan boya dokuları, mavi ve altın",
        ],
    },
    {
        "id": "interior_design",
        "label": "İç mekân tasarımı",
        "prompts": [
            "modern oturma odası, doğal ahşap, bol ışık",
            "sade çalışma odası, kitaplık ve bitkiler",
        ],
    },
    {
        "id": "historical_environments",
        "label": "Tarihî ortamlar",
        "prompts": [
            "efes antik kenti, mermer sütunlar, gün batımı",
            "osmanlı dönemi çarşı, taş kemerler",
        ],
    },
    {
        "id": "weather_scenes",
        "label": "Hava olayları",
        "prompts": [
            "yağmurlu gece şehri, ıslak sokak, neon yansımalar",
            "karlı orman, sabah sisi, sessizlik",
        ],
    },
    {
        "id": "everyday_objects",
        "label": "Günlük nesneler",
        "prompts": [
            "kahve fincanı ve defter, ahşap masa",
            "eski daktilo, sıcak lamba ışığı",
        ],
    },
    {
        "id": "turkish_cultural",
        "label": "Türk kültürel ortamları",
        "prompts": [
            "türk kahvesi, lokum ve geleneksel tepsi",
            "nevruz kutlaması, geleneksel kıyafetler, açık alan",
        ],
    },
]

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MIN_EDGE_PX = 512


@dataclass
class Case:
    index: int
    category: str
    category_label: str
    prompt: str

    @property
    def case_id(self) -> str:
        return f"{self.index:02d}_{self.category}"


def build_cases() -> List[Case]:
    cases: List[Case] = []
    for category in CATEGORIES:
        for prompt in category["prompts"]:  # type: ignore[index]
            cases.append(
                Case(
                    index=len(cases) + 1,
                    category=str(category["id"]),
                    category_label=str(category["label"]),
                    prompt=str(prompt),
                )
            )
    return cases


CASES: List[Case] = build_cases()


# ------------------------------------------------------------
# SIR TEMİZLEME
# ------------------------------------------------------------

def _secret_values() -> List[str]:
    names = (
        "CLOUDFLARE_API_TOKEN",
        "CF_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
        "CF_ACCOUNT_ID",
        "GEMINI_API_KEY",
    )
    values = []
    for name in names:
        value = (os.getenv(name) or "").strip()
        if len(value) >= 6:
            values.append(value)
    return values


def sanitize(text: object) -> str:
    """Hata metinlerinden sır değerlerini ve uzun token benzeri dizileri siler."""
    cleaned = str(text)
    for secret in _secret_values():
        cleaned = cleaned.replace(secret, "[GIZLI]")
    # Uzun alfanümerik dizileri (olası token) maskele.
    cleaned = re.sub(r"\b[A-Za-z0-9_\-]{32,}\b", "[GIZLI]", cleaned)
    return cleaned


# ------------------------------------------------------------
# YARDIMCILAR
# ------------------------------------------------------------

def artifact_dir() -> Path:
    override = (os.getenv("LUMINA_IMAGE_ARTIFACT_DIR") or "").strip()
    if override:
        path = Path(override)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = Path(os.getenv("TEMP") or ".") / f"lumina_gorsel_testleri_{stamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def image_bytes_of(image: "image_engine.GeneratedImage") -> bytes:
    if image.image_bytes:
        return image.image_bytes
    if image.image_base64:
        import base64

        return base64.b64decode(image.image_base64)
    return b""


def inspect_image(data: bytes) -> Dict[str, object]:
    """Boyut, format ve 'boş/tek renk' kontrolü. PIL yoksa yalnızca boyut döner."""
    info: Dict[str, object] = {"bytes": len(data)}
    try:
        from PIL import Image, ImageStat
    except Exception:  # noqa: BLE001 - Pillow opsiyonel
        info["inspection"] = "Pillow yok; yalnızca boyut doğrulandı"
        return info

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            info["format"] = img.format
            info["width"], info["height"] = img.size
            info["mode"] = img.mode
            gray = img.convert("L")
            stat = ImageStat.Stat(gray)
            info["luma_stddev"] = round(float(stat.stddev[0]), 2)
            info["uniform"] = float(stat.stddev[0]) < 2.0
    except Exception as exc:  # noqa: BLE001
        info["inspection"] = f"görsel açılamadı: {type(exc).__name__}"
        info["corrupt"] = True
    return info


def provider_ready() -> bool:
    return bool(
        image_engine.cloudflare_account_id() and image_engine.cloudflare_api_token()
    )


def run_case(case: Case, out_dir: Path) -> Dict[str, object]:
    record: Dict[str, object] = {
        "id": case.case_id,
        "index": case.index,
        "category": case.category,
        "category_label": case.category_label,
        "prompt": case.prompt,
        "status": "FAIL",
        "provider": None,
        "model": None,
        "mime_type": None,
        "latency_ms": None,
        "warnings": [],
        "error": None,
        "quality_review": "pending",
        "artifact": None,
        "image": {},
    }

    started = time.monotonic()
    try:
        image = image_engine.generate_image(case.prompt, aspect_ratio="1:1")
    except image_engine.ImageEngineError as exc:
        record["error"] = sanitize(exc.message)
        record["failures"] = [sanitize(item) for item in exc.failures]
        record["latency_ms"] = int((time.monotonic() - started) * 1000)
        return record
    except Exception as exc:  # noqa: BLE001 - beklenmeyen hata da raporlanır
        record["error"] = sanitize(f"{type(exc).__name__}: {exc}")
        record["latency_ms"] = int((time.monotonic() - started) * 1000)
        return record

    data = image_bytes_of(image)
    info = inspect_image(data)
    record["provider"] = image.provider
    record["model"] = image.model
    record["mime_type"] = image.mime_type
    record["latency_ms"] = image.latency_ms or int((time.monotonic() - started) * 1000)
    record["warnings"] = [sanitize(item) for item in image.warnings]
    record["image"] = info
    record["sha256"] = hashlib.sha256(data).hexdigest()

    problems: List[str] = []
    if not data:
        problems.append("görsel baytı boş")
    if len(data) > MAX_IMAGE_BYTES:
        problems.append(f"boyut sınırı aşıldı ({len(data)} bayt)")
    if image.mime_type not in ALLOWED_MIME:
        problems.append(f"beklenmeyen MIME türü: {image.mime_type}")
    if info.get("corrupt"):
        problems.append("görsel çözülemedi (bozuk veri)")
    width = info.get("width")
    height = info.get("height")
    if isinstance(width, int) and isinstance(height, int):
        if min(width, height) < MIN_EDGE_PX:
            problems.append(f"çözünürlük düşük: {width}x{height}")
    elif "inspection" not in info:
        problems.append("boyut okunamadı")
    if info.get("uniform"):
        problems.append("görsel tek renk/boş görünüyor")

    if problems:
        record["status"] = "WARN"
        record["problems"] = problems
    else:
        record["status"] = "PASS"

    if data:
        extension = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(image.mime_type, ".bin")
        target = out_dir / f"{case.case_id}{extension}"
        target.write_bytes(data)
        record["artifact"] = str(target)

    return record


def main() -> int:
    # Pollinations bu koşucuda her zaman kapalı.
    os.environ["LUMINA_ENABLE_POLLINATIONS"] = "0"
    os.environ.setdefault("LUMINA_IMAGE_PROVIDER_ORDER", "cloudflare")

    out_dir = artifact_dir()
    report: Dict[str, object] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider_order_requested": os.getenv("LUMINA_IMAGE_PROVIDER_ORDER"),
        "pollinations_enabled": image_engine.pollinations_enabled(),
        "providers": image_engine.provider_status(),
        "provider_order_effective": image_engine.provider_order(),
        "artifact_dir": str(out_dir),
        "total_cases": len(CASES),
        "status": "BLOCKED",
        "cases": [],
        "summary": {},
    }

    if not provider_ready():
        report["blocked_reason"] = (
            "CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN tanımlı değil. "
            "Hiçbir sağlayıcı çağrısı yapılmadı."
        )
        _write_report(out_dir, report)
        print("BLOCKED: Cloudflare anahtarı yok. Hiçbir istek atılmadı.")
        print(f"Rapor: {out_dir / 'metadata.json'}")
        return 2

    records: List[Dict[str, object]] = []
    delay = float(os.getenv("LUMINA_IMAGE_TEST_DELAY_SECS", "1.5") or 1.5)
    for position, case in enumerate(CASES):
        record = run_case(case, out_dir)
        records.append(record)
        print(
            f"[{case.index:02d}/{len(CASES)}] {record['status']:<4} "
            f"{case.category}/{case.prompt[:52]}"
        )
        if position < len(CASES) - 1 and delay > 0:
            time.sleep(delay)

    counts: Dict[str, int] = {}
    for record in records:
        counts[str(record["status"])] = counts.get(str(record["status"]), 0) + 1

    passed = counts.get("PASS", 0)
    warn = counts.get("WARN", 0)
    failed = counts.get("FAIL", 0)
    if passed == len(records):
        overall = "PASS"
    elif passed + warn > 0:
        overall = "PASS_WITH_WARNINGS"
    else:
        overall = "FAIL"

    report["cases"] = records
    report["status"] = overall
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["summary"] = {
        "pass": passed,
        "warn": warn,
        "fail": failed,
        "total": len(records),
        "quality_review": "pending (insan incelemesi gerekli)",
    }
    _write_report(out_dir, report)

    print()
    print(f"Özet: {passed} PASS, {warn} WARN, {failed} FAIL / {len(records)}")
    print(f"Görseller ve metadata: {out_dir}")
    print("Not: Görsel KALİTESİ otomatik değerlendirilmedi; insan incelemesi bekliyor.")
    return 0 if overall == "PASS" else 1


def _write_report(out_dir: Path, report: Dict[str, object]) -> None:
    target = out_dir / "metadata.json"
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Sır sızıntısına karşı son kontrol: dosyada anahtar değeri geçmesin.
    text = target.read_text(encoding="utf-8")
    for secret in _secret_values():
        if secret and secret in text:
            raise SystemExit(
                "GÜVENLİK: metadata dosyasında sır değeri bulundu; dosya yazılmadı."
            )


if __name__ == "__main__":
    sys.exit(main())
