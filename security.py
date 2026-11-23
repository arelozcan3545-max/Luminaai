# ============================================================
# LUMINA AI - DOSYA İŞLEME GÜVENLİK KATMANI
# Boyut, arşiv bombası, yol geçişi, kodlama ve zaman aşımı koruması.
# ============================================================

import os
import re
import io
import stat
import gzip
import bz2
import lzma
import tarfile
import zipfile
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable, Optional, Tuple, TypeVar
from html import unescape

T = TypeVar("T")

# ------------------------------------------------------------
# SINIRLAR (ortam değişkeniyle ayarlanabilir)
# ------------------------------------------------------------

def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


MAX_UPLOAD_BYTES = _env_int("LUMINA_MAX_UPLOAD_MB", 25) * 1024 * 1024
MAX_TEXT_CHARS = _env_int("LUMINA_MAX_TEXT_CHARS", 300_000)
MAX_ARCHIVE_ENTRIES = _env_int("LUMINA_MAX_ARCHIVE_ENTRIES", 2_000)
MAX_ARCHIVE_UNCOMPRESSED = _env_int("LUMINA_MAX_ARCHIVE_MB", 200) * 1024 * 1024
MAX_ENTRY_UNCOMPRESSED = _env_int("LUMINA_MAX_ENTRY_MB", 50) * 1024 * 1024
MAX_COMPRESSION_RATIO = _env_int("LUMINA_MAX_COMPRESSION_RATIO", 150)
PARSE_TIMEOUT_SECS = _env_int("LUMINA_PARSE_TIMEOUT_SECS", 20)


# ------------------------------------------------------------
# HATA MODELİ
# ------------------------------------------------------------

class FileAnalysisError(Exception):
    """Kullanıcıya Türkçe mesajla gösterilecek dosya analiz hatası."""

    def __init__(self, message: str, code: str = "file_error", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


# ------------------------------------------------------------
# YARDIMCILAR
# ------------------------------------------------------------

_UNSAFE_NAME_RE = re.compile(r"[\x00-\x1f\x7f]")


def normalize_filename(filename: Optional[str]) -> str:
    """Yol bileşenlerini ve kontrol karakterlerini temizler."""
    name = (filename or "belge").strip()
    name = name.replace("\\", "/").split("/")[-1]
    name = _UNSAFE_NAME_RE.sub("", name).strip()
    if name in ("", ".", ".."):
        name = "belge"
    return name[:255]


def looks_binary(data: bytes, sample: int = 8192) -> bool:
    """Metin olmayan içerikte null/control byte oranını kontrol eder."""
    chunk = data[:sample]
    if not chunk:
        return False
    if b"\x00" in chunk:
        return True
    control = sum(1 for b in chunk if b < 9 or (13 < b < 32))
    return control / max(1, len(chunk)) > 0.20


def decode_text(data: bytes) -> Tuple[str, str]:
    """BOM ve Türkçe kodlamaları dikkate alarak metni çözer."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="replace"), "utf-8-sig"
    if data.startswith(b"\xff\xfe\x00\x00") or data.startswith(b"\x00\x00\xfe\xff"):
        return data.decode("utf-32", errors="replace"), "utf-32"
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace"), "utf-16"
    for encoding in ("utf-8", "cp1254", "latin-1"):
        try:
            return data.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def clean_text(text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    """Satır sonlarını normalize eder, kontrol karakterlerini temizler ve sınırlar."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _UNSAFE_NAME_RE.sub("", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()[:max_chars]


class _HTMLTextExtractor:
    """Bağımlılıksız, betikleri yok sayan güvenli HTML metin çıkarıcı."""

    def __init__(self):
        from html.parser import HTMLParser

        self._parser_cls = HTMLParser
        self.parts = []
        self.skip_depth = 0
        self.title = ""
        self._in_title = False

    def feed(self, html_text: str) -> str:
        outer = self

        class Parser(self._parser_cls):
            def handle_starttag(self, tag, attrs):
                tag = tag.lower()
                if tag in ("script", "style", "noscript", "template"):
                    outer.skip_depth += 1
                elif tag == "title":
                    outer._in_title = True
                if tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
                    outer.parts.append("\n")

            def handle_endtag(self, tag):
                tag = tag.lower()
                if tag in ("script", "style", "noscript", "template") and outer.skip_depth:
                    outer.skip_depth -= 1
                elif tag == "title":
                    outer._in_title = False
                if tag in ("p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
                    outer.parts.append("\n")

            def handle_data(self, data):
                if outer.skip_depth:
                    return
                if outer._in_title:
                    outer.title += data
                    return
                outer.parts.append(data)

        parser = Parser(convert_charrefs=True)
        try:
            parser.feed(html_text)
            parser.close()
        except Exception:
            # Bozuk HTML: kaba etiket temizliğiyle devam et
            return strip_markup(html_text)
        return clean_text(unescape("".join(self.parts)))


def html_to_text(html_text: str) -> Tuple[str, str]:
    extractor = _HTMLTextExtractor()
    text = extractor.feed(html_text)
    return text, clean_text(extractor.title, 200)


def strip_markup(markup: str) -> str:
    """XML/HTML benzeri işaretlemeden düz metin çıkarır (betikler dâhil edilmez)."""
    if not markup:
        return ""
    text = re.sub(r"<!--[\s\S]*?-->", " ", markup)
    text = re.sub(r"<!\[CDATA\[([\s\S]*?)\]\]>", r"\1", text)
    text = re.sub(r"<\s*(script|style|noscript)[^>]*>[\s\S]*?<\s*/\s*\1\s*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*(p|div|li|tr|h[1-6]|section|article)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]{0,2000}>", " ", text)
    return clean_text(unescape(text))


# ------------------------------------------------------------
# ARŞİV GÜVENLİĞİ
# ------------------------------------------------------------

def _is_unsafe_archive_name(name: str) -> bool:
    if not name or "\x00" in name:
        return True
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return True
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    return any(p == ".." for p in parts)


def validate_zip(zf: zipfile.ZipFile) -> None:
    """Zip bomb, şifreleme, sembolik bağ ve yol geçişi denetimi."""
    infos = zf.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise FileAnalysisError(
            f"Arşivde çok fazla dosya var ({len(infos)}). Azami {MAX_ARCHIVE_ENTRIES} desteklenir.",
            code="archive_too_many_entries", status_code=422,
        )

    total_uncompressed = 0
    for info in infos:
        name = info.filename
        if _is_unsafe_archive_name(name):
            raise FileAnalysisError(
                "Arşivde güvenli olmayan bir dosya yolu tespit edildi (path traversal).",
                code="archive_path_traversal", status_code=422,
            )
        if info.flag_bits & 0x1:
            raise FileAnalysisError(
                "Şifreli arşivler güvenlik nedeniyle analiz edilemez.",
                code="archive_encrypted", status_code=422,
            )
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise FileAnalysisError(
                "Arşivde sembolik bağlantı tespit edildi; güvenlik nedeniyle reddedildi.",
                code="archive_symlink", status_code=422,
            )
        if info.file_size > MAX_ENTRY_UNCOMPRESSED:
            raise FileAnalysisError(
                "Arşivdeki bir dosya izin verilen boyutu aşıyor.",
                code="archive_entry_too_large", status_code=422,
            )
        if info.file_size > 1024 * 1024:
            ratio = info.file_size / max(1, info.compress_size)
            if ratio > MAX_COMPRESSION_RATIO:
                raise FileAnalysisError(
                    "Arşivde aşırı sıkıştırma oranı tespit edildi (zip bomb şüphesi).",
                    code="archive_bomb", status_code=422,
                )
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED:
            raise FileAnalysisError(
                "Arşivin açılmış boyutu güvenlik sınırını aşıyor.",
                code="archive_too_large", status_code=422,
            )


def open_safe_zip(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise FileAnalysisError("Bozuk veya geçersiz ZIP arşivi.", code="bad_zip", status_code=422) from exc
    validate_zip(zf)
    return zf


def safe_zip_read(zf: zipfile.ZipFile, name: str, max_bytes: int = 20 * 1024 * 1024) -> bytes:
    try:
        info = zf.getinfo(name)
    except KeyError as exc:
        raise FileAnalysisError(f"Arşiv içinde beklenen dosya bulunamadı: {name}", code="missing_entry") from exc
    if info.file_size > max_bytes:
        raise FileAnalysisError(
            "Arşiv içindeki belge bileşeni güvenlik sınırından büyük.",
            code="entry_too_large", status_code=422,
        )
    try:
        return zf.read(info)
    except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
        raise FileAnalysisError("Arşiv içeriği okunamadı (bozuk veya şifreli).", code="zip_read_failed", status_code=422) from exc


def scan_zip_macros(zf: zipfile.ZipFile) -> bool:
    """Office dosyalarında VBA makro varlığını tespit eder."""
    for name in zf.namelist():
        low = name.lower()
        if low.endswith("vbaproject.bin") or low.endswith("vbadata.xml"):
            return True
    return False


def validate_tar(tf: tarfile.TarFile) -> int:
    count = 0
    total = 0
    for member in tf:
        count += 1
        if count > MAX_ARCHIVE_ENTRIES:
            raise FileAnalysisError(
                "Arşivde çok fazla dosya var.", code="archive_too_many_entries", status_code=422
            )
        if _is_unsafe_archive_name(member.name):
            raise FileAnalysisError(
                "Arşivde güvenli olmayan dosya yolu tespit edildi.",
                code="archive_path_traversal", status_code=422,
            )
        if member.issym() or member.islnk():
            raise FileAnalysisError(
                "Arşivde bağlantı dosyası tespit edildi; reddedildi.",
                code="archive_symlink", status_code=422,
            )
        if member.size > MAX_ENTRY_UNCOMPRESSED:
            raise FileAnalysisError(
                "Arşivdeki bir dosya izin verilen boyutu aşıyor.",
                code="archive_entry_too_large", status_code=422,
            )
        total += member.size
        if total > MAX_ARCHIVE_UNCOMPRESSED:
            raise FileAnalysisError(
                "Arşivin açılmış boyutu güvenlik sınırını aşıyor.",
                code="archive_too_large", status_code=422,
            )
    return count


def describe_gzip(data: bytes) -> dict:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
            original_name = getattr(gz, "name", "") or ""
            chunk = gz.read(min(MAX_ENTRY_UNCOMPRESSED, 4 * 1024 * 1024) + 1)
            if len(chunk) > MAX_ENTRY_UNCOMPRESSED or len(chunk) > 4 * 1024 * 1024:
                raise FileAnalysisError(
                    "Sıkıştırılmış dosyanın açılmış boyutu güvenlik sınırını aşıyor.",
                    code="archive_too_large", status_code=422,
                )
            return {"original_name": original_name, "uncompressed_sample_bytes": len(chunk)}
    except FileAnalysisError:
        raise
    except Exception as exc:
        raise FileAnalysisError("GZIP dosyası okunamadı.", code="bad_archive", status_code=422) from exc


# ------------------------------------------------------------
# ZAMAN AŞIMLI ÇALIŞTIRMA
# ------------------------------------------------------------

_PARSE_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lumina-parse")


def run_with_timeout(fn: Callable[[], T], timeout: int = PARSE_TIMEOUT_SECS) -> T:
    future = _PARSE_EXECUTOR.submit(fn)
    try:
        return future.result(timeout=timeout)
    except FutureTimeout as exc:
        future.cancel()
        raise FileAnalysisError(
            f"Dosya ayrıştırma {timeout} saniyede tamamlanmadı; dosya çok karmaşık olabilir.",
            code="parse_timeout", status_code=422,
        ) from exc
