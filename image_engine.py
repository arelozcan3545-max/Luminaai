# ============================================================
# LUMINA AI - GÖRSEL ÜRETİM SAĞLAYICI SOYUTLAMA KATMANI
# ============================================================
# Amaç: Sağlayıcıya özgü kodun tamamını tek yerde toplamak ve
# frontend'i hiçbir sağlayıcıya bağlamamak.
#
# Sağlayıcı sırası (ücretsiz erişim ilkesi):
#   1. Gemini Nano Banana  -> en iyi Türkçe anlama + fotogerçekçilik
#   2. Cloudflare Workers AI FLUX.1-schnell -> ücretsiz 10k neuron/gün,
#      Cloudflare uyumlu; kare çıktı sınırı vardır.
#   3. Pollinations Classic -> DENEYSEL, VARSAYILAN OLARAK KAPALI.
#      Üretimde birincil/otomatik sağlayıcı OLAMAZ. Yalnızca açıkça
#      LUMINA_ENABLE_POLLINATIONS=1 verilirse ve son sırada devreye girer.
#      Tek model, <=768x768, JPEG + logo, IP başına 45 saniyede 1 istek.
#
# ÖNEMLİ: Bu modül sır değerlerini loglamaz, yanıtlamaz veya döndürmez.
# Yalnızca "yapılandırılmış mı" bilgisini paylaşır.
# ============================================================

from __future__ import annotations

import base64
import logging
import io
import threading
from pathlib import Path
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

import models_provider as _models_provider
from models_provider import GEMINI_IMAGE_MODEL, ProviderError

logger = logging.getLogger("LuminaImageEngine")

PROVIDER_GEMINI = "gemini"
PROVIDER_CLOUDFLARE = "cloudflare"
PROVIDER_POLLINATIONS = "pollinations"

CLOUDFLARE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
CLOUDFLARE_STEPS = 8
POLLINATIONS_MAX_AREA = 768 * 768
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024

# Cloudflare Workers AI REST uç noktası (Python backend'den çağrılır; Worker
# dağıtımı gerektirmez, bu yüzden mevcut mimariyle uyumludur).
CLOUDFLARE_AI_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
)

ASPECT_DIMENSIONS = {
    "1:1": (1024, 1024),
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "4:3": (1024, 768),
    "3:2": (1080, 720),
}


class ImageEngineError(RuntimeError):
    """Tüm sağlayıcılar başarısız olduğunda fırlatılır (Türkçe kullanıcı mesajı)."""

    def __init__(self, message: str, *, failures: Optional[List[str]] = None):
        self.message = message
        self.failures = failures or []
        super().__init__(message)


class ProviderFailure(RuntimeError):
    """Tek bir sağlayıcının başarısız olması; sıradaki sağlayıcı denenir."""

    def __init__(self, provider: str, message: str, *, status_code: int = 502,
                 transient: bool = False):
        self.provider = provider
        self.message = message
        self.status_code = status_code
        self.transient = transient
        super().__init__(f"{provider}: {message}")


@dataclass
class GeneratedImage:
    """Sağlayıcıdan dönen doğrulanmış görsel."""

    provider: str
    model: str
    mime_type: str = "image/png"
    image_base64: Optional[str] = None
    image_bytes: Optional[bytes] = None
    source_url: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    latency_ms: int = 0

    @property
    def image_uri(self) -> str:
        if self.image_base64:
            return f"data:{self.mime_type};base64,{self.image_base64}"
        if self.image_bytes:
            encoded = base64.b64encode(self.image_bytes).decode("ascii")
            return f"data:{self.mime_type};base64,{encoded}"
        return self.source_url or ""


# ------------------------------------------------------------
# YAPILANDIRMA (sır değeri döndürülmez)
# ------------------------------------------------------------

def gemini_api_key() -> str:
    """Gemini anahtarını ÇAĞRI ANINDA okur (test/rotasyon güvenli)."""
    return (_models_provider.GEMINI_API_KEY or "").strip()


def cloudflare_account_id() -> str:
    return (
        os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        or os.getenv("CF_ACCOUNT_ID", "").strip()
    )


def cloudflare_api_token() -> str:
    return (
        os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        or os.getenv("CF_API_TOKEN", "").strip()
    )


def pollinations_enabled() -> bool:
    """Deneysel Pollinations adaptörü VARSAYILAN OLARAK KAPALIDIR.

    - Üretimde birincil sağlayıcı olarak kullanılamaz.
    - Yalnızca açık opt-in (`LUMINA_ENABLE_POLLINATIONS=1`) ile devreye girer.
    - `LUMINA_DISABLE_POLLINATIONS=1` her zaman kapatır (geriye uyumluluk).
    """
    if os.getenv("LUMINA_DISABLE_POLLINATIONS", "0").strip() == "1":
        return False
    return os.getenv("LUMINA_ENABLE_POLLINATIONS", "0").strip() == "1"


# Varsayılan sıra: önce kalite (Gemini), sonra ücretsiz katman (Cloudflare).
# `LUMINA_IMAGE_PROVIDER_ORDER` ile açıkça değiştirilebilir (ör. ücretsiz
# öncelikli çalışma için "cloudflare,gemini").
DEFAULT_PROVIDER_ORDER: Tuple[str, ...] = (PROVIDER_GEMINI, PROVIDER_CLOUDFLARE)


def _requested_provider_order() -> List[str]:
    raw = os.getenv("LUMINA_IMAGE_PROVIDER_ORDER", "").strip()
    if not raw:
        return list(DEFAULT_PROVIDER_ORDER)
    parsed: List[str] = []
    for item in raw.split(","):
        name = item.strip().lower()
        if name in (PROVIDER_GEMINI, PROVIDER_CLOUDFLARE) and name not in parsed:
            parsed.append(name)
    return parsed


def provider_order() -> List[str]:
    """Yalnızca yapılandırılmış sağlayıcıları, açık sırayla döndürür.

    - Birincil/ikincil sıra `LUMINA_IMAGE_PROVIDER_ORDER` ile belirlenir.
    - Pollinations listenin EN SONUNDA ve yalnızca açıkça etkinleştirilmişse
      yer alır; hiçbir zaman varsayılan üretim sağlayıcısı olamaz.
    """
    if os.getenv('LUMINA_IMAGE_PROVIDER_ORDER', '').strip().lower() == 'local':
        if _local_image_available():
            return ["local"]
        return [PROVIDER_CLOUDFLARE] if cloudflare_account_id() and cloudflare_api_token() else []
    configured = {
        PROVIDER_GEMINI: bool(gemini_api_key()),
        PROVIDER_CLOUDFLARE: bool(cloudflare_account_id() and cloudflare_api_token()),
    }

    order = [name for name in _requested_provider_order() if configured.get(name)]

    # Güvenlik ağı: sıra yanlış yazıldığı için yapılandırılmış bir sağlayıcı
    # sessizce devre dışı kalmasın.
    if not order:
        order = [name for name in DEFAULT_PROVIDER_ORDER if configured.get(name)]

    if pollinations_enabled():
        order.append(PROVIDER_POLLINATIONS)
    return order


def provider_status() -> List[Dict[str, object]]:
    """Sağlayıcı durumunu sır içermeden raporlar (health endpoint için)."""
    return [
        {
            "id": "local", "configured": _local_image_available(),
            "model": "Z-Image-Turbo Q4_K", "billing": "local", "keyless": True,
        },
        {
            "id": PROVIDER_GEMINI,
            "configured": bool(gemini_api_key()),
            "model": GEMINI_IMAGE_MODEL,
            "billing": "paid",
            "free_tier": "API'de ücretsiz katman YOK (resmî fiyat: ~0,034 USD/1K görsel)",
            "keyless": False,
        },
        {
            "id": PROVIDER_CLOUDFLARE,
            "configured": bool(cloudflare_account_id() and cloudflare_api_token()),
            "model": CLOUDFLARE_MODEL,
            "billing": "free_tier",
            "free_tier": "10.000 neuron/gün (kare çıktı)",
            "keyless": False,
        },
        {
            "id": PROVIDER_POLLINATIONS,
            "configured": pollinations_enabled(),
            "enabled": pollinations_enabled(),
            "default_enabled": False,
            "experimental": True,
            "production_allowed": False,
            "model": "classic-default",
            "free_tier": (
                "anahtarsız; IP başına 45 sn ara, <=768x768, logolu — "
                "varsayılan kapalı deneysel adaptör"
            ),
            "keyless": True,
        },
    ]


# ------------------------------------------------------------
# TEMSİL / GİYSİ KORUMASI (sağlayıcı entegrasyon katmanı)
# ------------------------------------------------------------
# Amaç: kadın/erkek karakterler için varsayılan cinselleştirmeyi engellemek.
# Kullanıcı giysi belirttiyse ASLA değiştirilmez.

_PERSON_RE = re.compile(
    r"\b(kad[ıi]n|k[ıi]z|erkek|adam|bayan|han[ıi]m|portre|insan|ki[şs]i|"
    r"woman|women|girl|man|men|person|people|portrait|model|character|"
    r"karekter|karakter|female|male)\b",
    re.IGNORECASE,
)

_CLOTHING_RE = re.compile(
    r"\b(elbise|giysi|kıyafet|kiyafet|ceket|gömlek|gomlek|pantolon|etek|"
    r"kazak|mont|palto|kaban|üniforma|uniforma|takım elbise|takim elbise|"
    r"önlük|onluk|hırka|hirka|bluz|yelek|tişört|tisort|tshirt|şort|sort|"
    r"mayo|forma|tayt|kot|eşarp|esarp|atkı|atki|bere|şapka|sapka|eldiven|"
    r"ayakkabı|ayakkabi|bot|çizme|cizme|"
    r"dress|shirt|jacket|coat|pants|trousers|skirt|sweater|suit|uniform|"
    r"wear|wearing|outfit|attire|kostüm|kostum|costume|armor|zırh|zirh|"
    r"hoodie|jean|jeans|gown|robe|vest|apron|scarf|hat|gloves|shoes|boots|"
    r"swimwear|swimsuit)\b",
    re.IGNORECASE,
)

REPRESENTATION_GUARD = (
    "fully clothed in ordinary modest everyday clothing, natural pose, "
    "no nudity, no revealing outfit, no sexualization"
)


def apply_representation_guard(prompt: str) -> str:
    """Kişi içeren ve giysi belirtmeyen promptlara ölçülü bir giysi yönergesi ekler.

    Kullanıcı giysi belirttiyse metne DOKUNULMAZ; istenen kıyafet korunur.
    """
    if not prompt:
        return prompt
    if not _PERSON_RE.search(prompt):
        return prompt
    if _CLOTHING_RE.search(prompt):
        return prompt
    if REPRESENTATION_GUARD.split(",")[0] in prompt.lower():
        return prompt
    return f"{prompt}, {REPRESENTATION_GUARD}"


# ------------------------------------------------------------
# YARDIMCILAR
# ------------------------------------------------------------

def _dimensions_for(aspect_ratio: str) -> Tuple[int, int]:
    return ASPECT_DIMENSIONS.get(aspect_ratio, (1024, 1024))


def _pollinations_dimensions(aspect_ratio: str) -> Tuple[int, int]:
    """Pollinations Classic <=768x768 alan sınırına ölçeği indirir."""
    width, height = _dimensions_for(aspect_ratio)
    scale = (POLLINATIONS_MAX_AREA / float(width * height)) ** 0.5
    if scale < 1.0:
        width = max(256, int(width * scale) // 8 * 8)
        height = max(256, int(height * scale) // 8 * 8)
    return width, height


def _decode_base64_image(value: str, *, provider: str) -> bytes:
    clean = (value or "").strip()
    if clean.startswith("data:"):
        clean = clean.partition(",")[2]
    try:
        data = base64.b64decode(clean, validate=True)
    except Exception as exc:  # noqa: BLE001 - sağlayıcı çıktısı güvenilmez
        raise ProviderFailure(provider, "Sağlayıcı geçersiz görüntü verisi döndürdü.") from exc
    if len(data) < 512:
        raise ProviderFailure(provider, "Sağlayıcı boş/bozuk görüntü döndürdü.")
    return data


def _extract_cloudflare_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return f"HTTP {response.status_code}"
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict) and first.get("message"):
            return str(first["message"])[:200]
    return f"HTTP {response.status_code}"


# ------------------------------------------------------------
# SAĞLAYICILAR
# ------------------------------------------------------------

def _generate_gemini(prompt: str, aspect_ratio: str) -> GeneratedImage:
    started = time.monotonic()
    try:
        result = _models_provider.call_gemini_image(prompt, aspect_ratio=aspect_ratio)
    except ProviderError as exc:
        raise ProviderFailure(
            PROVIDER_GEMINI,
            f"Gemini görsel üretimi başarısız: {type(exc).__name__}",
            status_code=503,
            transient=True,
        ) from exc

    image_b64 = (result or {}).get("image_base64") or ""
    mime = (result or {}).get("mime_type") or "image/png"
    if not image_b64:
        raise ProviderFailure(PROVIDER_GEMINI, "Gemini görüntü verisi döndürmedi.")
    _decode_base64_image(image_b64, provider=PROVIDER_GEMINI)
    if not mime.lower().startswith("image/"):
        mime = "image/png"
    return GeneratedImage(
        provider=PROVIDER_GEMINI,
        model=GEMINI_IMAGE_MODEL,
        mime_type=mime,
        image_base64=image_b64,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def _generate_cloudflare(prompt: str, aspect_ratio: str) -> GeneratedImage:
    account_id = cloudflare_account_id()
    token = cloudflare_api_token()
    if not account_id or not token:
        raise ProviderFailure(PROVIDER_CLOUDFLARE, "Cloudflare Workers AI yapılandırılmamış.")

    started = time.monotonic()
    url = CLOUDFLARE_AI_URL.format(account_id=account_id, model=CLOUDFLARE_MODEL)
    payload = {"prompt": prompt[:2048], "steps": CLOUDFLARE_STEPS}
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=(10, 90),
        )
    except requests.RequestException as exc:
        raise ProviderFailure(
            PROVIDER_CLOUDFLARE,
            f"Cloudflare Workers AI bağlantısı başarısız: {type(exc).__name__}",
            status_code=503,
            transient=True,
        ) from exc

    if not response.ok:
        status = response.status_code
        public_reason = {
            400: "Cloudflare görsel isteğini reddetti.",
            401: "Cloudflare API belirteci doğrulanamadı.",
            403: "Cloudflare erişimi reddetti. Hesap kimliğini ve belirtecin Workers AI çalıştırma iznini kontrol edin.",
            404: "Cloudflare hesabı veya görsel modeli bulunamadı.",
            429: "Cloudflare istek veya günlük kullanım sınırına ulaşıldı.",
        }.get(status, "Cloudflare görsel servisi isteği tamamlayamadı.")
        try:
            errors = response.json().get("errors", [])
            code = errors[0].get("code") if errors else None
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            code = None
        reference = f"HTTP {status}" + (f", CF {code}" if isinstance(code, int) else "")
        raise ProviderFailure(PROVIDER_CLOUDFLARE, f"{public_reason} ({reference})",
                              status_code=status, transient=status == 429 or status >= 500)

    mime_type = response.headers.get("Content-Type", "").split(";")[0].lower()
    if mime_type in ("image/png", "image/jpeg", "image/webp"):
        image_bytes = response.content
        if not image_bytes or len(image_bytes) > MAX_DOWNLOAD_BYTES:
            raise ProviderFailure(PROVIDER_CLOUDFLARE, "Cloudflare geçerli boyutta bir görsel döndürmedi.")
    else:
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderFailure(PROVIDER_CLOUDFLARE, "Cloudflare yanıtında görsel bulunamadı.") from exc
        result = body.get("result", body) if isinstance(body, dict) else None
        value = result.get("image") if isinstance(result, dict) else result
        if not isinstance(value, str) or not value:
            raise ProviderFailure(PROVIDER_CLOUDFLARE, "Cloudflare yanıtında görsel bulunamadı.")
        image_bytes = _decode_base64_image(value, provider=PROVIDER_CLOUDFLARE)
        mime_type = "image/jpeg"
    warnings: List[str] = []
    if aspect_ratio != "1:1":
        warnings.append(
            "Cloudflare FLUX.1-schnell kare (1:1) üretir; istenen en-boy oranı "
            "sağlayıcı tarafından desteklenmiyor."
        )
    return GeneratedImage(
        provider=PROVIDER_CLOUDFLARE,
        model=CLOUDFLARE_MODEL,
        mime_type=mime_type,
        image_bytes=image_bytes,
        warnings=warnings,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def pollinations_url(prompt: str, aspect_ratio: str = "1:1", seed: Optional[int] = None) -> str:
    """Pollinations Classic API'nin GERÇEKTEN desteklediği parametrelerle URL üretir.

    Desteklenmeyen eski parametreler (`model`, `nologo`, `enhance`) bilinçli
    olarak gönderilmez; API bunları yok saydığı için yanıltıcı olurdu.
    """
    width, height = _pollinations_dimensions(aspect_ratio)
    safe_seed = seed if isinstance(seed, int) and seed > 0 else random.randint(10000, 999999)
    encoded = quote(prompt, safe="")
    return (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}&seed={safe_seed}&safe=true"
    )


POLLINATIONS_TRANSIENT_RETRIES = 1
POLLINATIONS_RETRY_DELAY_SECS = 2.5


def _pollinations_attempt(
    prompt: str, aspect_ratio: str, started: float
) -> GeneratedImage:
    """Tek bir Pollinations denemesi (retry mantığı çağıranda)."""
    url = pollinations_url(prompt, aspect_ratio)
    try:
        response = requests.get(url, timeout=(5, 60), stream=True)
    except requests.RequestException as exc:
        raise ProviderFailure(
            PROVIDER_POLLINATIONS,
            f"Pollinations bağlantısı başarısız: {type(exc).__name__}",
            status_code=503,
            transient=True,
        ) from exc

    try:
        if response.status_code == 402:
            retry_after = response.headers.get("Retry-After", "")
            extra = f" (yeniden deneme: {retry_after} sn)" if retry_after else ""
            raise ProviderFailure(
                PROVIDER_POLLINATIONS,
                "Pollinations ücretsiz istek sınırı: IP başına 45 saniyede 1 görsel"
                + extra,
                status_code=429,
                transient=True,
            )
        content_type = (response.headers.get("Content-Type") or "").lower()
        if response.status_code != 200 or not content_type.startswith("image/"):
            raise ProviderFailure(
                PROVIDER_POLLINATIONS,
                f"Pollinations görüntü döndürmedi (HTTP {response.status_code}).",
                status_code=502,
                transient=response.status_code >= 500,
            )
        chunks: List[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise ProviderFailure(
                    PROVIDER_POLLINATIONS,
                    "Pollinations yanıtı izin verilen boyutu aştı.",
                )
            chunks.append(chunk)
        image_bytes = b"".join(chunks)
        if len(image_bytes) < 512:
            raise ProviderFailure(PROVIDER_POLLINATIONS, "Pollinations boş görüntü döndürdü.")
    finally:
        response.close()

    mime = content_type.split(";")[0] or "image/jpeg"
    return GeneratedImage(
        provider=PROVIDER_POLLINATIONS,
        model="classic-default",
        mime_type=mime,
        image_bytes=image_bytes,
        source_url=url,
        warnings=[
            "Pollinations Classic tek model kullanır, en fazla 768x768 üretir ve "
            "görsele küçük bir logo ekler."
        ],
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def _generate_pollinations(prompt: str, aspect_ratio: str) -> GeneratedImage:
    if not pollinations_enabled():
        raise ProviderFailure(PROVIDER_POLLINATIONS, "Pollinations devre dışı (LUMINA_DISABLE_POLLINATIONS=1).")

    started = time.monotonic()
    attempt = 0
    while True:
        try:
            return _pollinations_attempt(prompt, aspect_ratio, started)
        except ProviderFailure as exc:
            # 402/429 (ücretsiz istek sınırı) ASLA yeniden denenmez; aksi halde
            # IP bir sonraki isteği de yakar. Yalnızca geçici 5xx/ağ hataları
            # bir kez yeniden denenir (canlı testte 6 hatanın 5'i bu şekilde
            # tekrar denemede başarılı oldu).
            retryable = exc.transient and exc.status_code not in (402, 429)
            if not retryable or attempt >= POLLINATIONS_TRANSIENT_RETRIES:
                raise
            attempt += 1
            logger.info(
                "Pollinations geçici hatası (%s); 1 kez yeniden denenecek.",
                exc.message,
            )
            time.sleep(POLLINATIONS_RETRY_DELAY_SECS)


# ------------------------------------------------------------
# GENEL GİRİŞ NOKTASI
# ------------------------------------------------------------

_LOCAL_MODEL = Path(__file__).resolve().parent / ".models" / "z-image-turbo"
_local_lock = threading.Lock()

def _local_image_available() -> bool:
    return os.name == "nt" and all((_LOCAL_MODEL / name).is_file() for name in (
        "sd-cli.exe", "z_image_turbo-Q4_K.gguf", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf", "ae.safetensors",
    ))


def _generate_local(prompt: str, aspect_ratio: str) -> GeneratedImage:
    import subprocess
    from tempfile import TemporaryDirectory
    from PIL import Image
    if not _local_lock.acquire(blocking=False):
        raise ProviderFailure("local", "Görsel motoru meşgul.")
    started = time.monotonic()
    try:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "result.png"
            w, h = _dimensions_for(aspect_ratio)
            scale = 1024 / max(w,h)
            args = [str(_LOCAL_MODEL / "sd-cli.exe"),
                    "--diffusion-model", str(_LOCAL_MODEL / "z_image_turbo-Q4_K.gguf"),
                    "--llm", str(_LOCAL_MODEL / "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
                    "--vae", str(_LOCAL_MODEL / "ae.safetensors"), "--steps", "8",
                    "--cfg-scale", "1", "--offload-to-cpu", "-W", str(round(w*scale/16)*16),
                    "-H", str(round(h*scale/16)*16), "-p", prompt, "-o", str(output)]
            subprocess.run(args, cwd=_LOCAL_MODEL, timeout=480, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with Image.open(output) as image:
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
            return GeneratedImage(provider="local", model="Z-Image-Turbo Q4_K", image_bytes=buffer.getvalue(),
                                  latency_ms=round(1000*(time.monotonic()-started)))
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProviderFailure("local", "Z-Image-Turbo üretimi tamamlanamadı.") from exc
    finally:
        _local_lock.release()

_GENERATORS = {
    "local": _generate_local,
    PROVIDER_GEMINI: _generate_gemini,
    PROVIDER_CLOUDFLARE: _generate_cloudflare,
    PROVIDER_POLLINATIONS: _generate_pollinations,
}


def generate_image(prompt: str, aspect_ratio: str = "1:1") -> GeneratedImage:
    """Sırayla sağlayıcıları dener; ilk başarılı görseli döndürür.

    Hiçbiri başarılı olmazsa `ImageEngineError` fırlatır. Hata mesajı
    kullanıcıya gösterilebilir; sır veya ham sağlayıcı yanıtı içermez.
    """
    order = provider_order()
    if not order:
        raise ImageEngineError(
            "Görsel sağlayıcısı yapılandırılmamış. Yönetici Gemini veya "
            "Cloudflare Workers AI anahtarı tanımlamalıdır."
        )

    guarded_prompt = apply_representation_guard(prompt)
    failures: List[str] = []
    cloudflare_reason = None

    for provider in order:
        try:
            image = _GENERATORS[provider](guarded_prompt, aspect_ratio)
            logger.info(
                "Görsel üretildi: sağlayıcı=%s model=%s süre=%dms",
                image.provider,
                image.model,
                image.latency_ms,
            )
            return image
        except ProviderFailure as exc:
            if provider == PROVIDER_CLOUDFLARE:
                cloudflare_reason = exc.message
            failures.append(f"{provider}: {exc.message}")
            logger.warning("Görsel sağlayıcısı başarısız (%s): %s", provider, exc.message)
        except Exception as exc:  # noqa: BLE001 - beklenmeyen sağlayıcı hatası
            failures.append(f"{provider}: {type(exc).__name__}")
            logger.exception("Görsel sağlayıcısında beklenmeyen hata: %s", provider)

    raise ImageEngineError(
        (cloudflare_reason or "Görsel sağlayıcıları isteği tamamlayamadı.") + " Kotanız tüketilmedi.",
        failures=failures,
    )


__all__ = [
    "GeneratedImage",
    "ImageEngineError",
    "ProviderFailure",
    "PROVIDER_CLOUDFLARE",
    "PROVIDER_GEMINI",
    "PROVIDER_POLLINATIONS",
    "apply_representation_guard",
    "cloudflare_account_id",
    "cloudflare_api_token",
    "generate_image",
    "gemini_api_key",
    "pollinations_url",
    "provider_order",
    "provider_status",
]
