# ============================================================
# LUMINA AI - DOSYA TÜRÜ ALGILAMA
# Uzantı + MIME + sihirli baytlar + iç yapı + içerik sezgisi.
# ============================================================

import re
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .security import (
    FileAnalysisError,
    open_safe_zip,
    safe_zip_read,
    looks_binary,
    decode_text,
)

# ------------------------------------------------------------
# FORMAT KAYDI
# ------------------------------------------------------------

CATEGORY_LABELS_TR = {
    "document": "Metin / Belge",
    "spreadsheet": "Tablo",
    "presentation": "Sunum",
    "image": "Görsel",
    "audio": "Ses",
    "video": "Video",
    "code": "Kaynak Kod",
    "archive": "Arşiv",
    "executable": "Çalıştırılabilir Dosya",
    "unknown": "Bilinmeyen",
}


@dataclass(frozen=True)
class FormatInfo:
    key: str
    label: str
    category: str
    mime: str
    extensions: Tuple[str, ...]
    text_capable: bool = True
    legacy: bool = False
    macro_enabled: bool = False


FORMATS: Dict[str, FormatInfo] = {}


def _register(key: str, label: str, category: str, mime: str, exts, **kwargs):
    FORMATS[key] = FormatInfo(key, label, category, mime, tuple(exts), **kwargs)


# Belgeler
_register("txt", "Düz Metin", "document", "text/plain", [".txt", ".log"])
_register("md", "Markdown", "document", "text/markdown", [".md", ".markdown"])
_register("rtf", "Zengin Metin (RTF)", "document", "application/rtf", [".rtf"])
_register("pdf", "PDF Belgesi", "document", "application/pdf", [".pdf"])
_register("docx", "Word Belgesi (DOCX)", "document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", [".docx"])
_register("docm", "Word Belgesi (Makrolu)", "document", "application/vnd.ms-word.document.macroEnabled.12", [".docm"], macro_enabled=True)
_register("odt", "OpenDocument Metin", "document", "application/vnd.oasis.opendocument.text", [".odt"])
_register("epub", "E-Kitap (EPUB)", "document", "application/epub+zip", [".epub"])
_register("html", "HTML Belgesi", "document", "text/html", [".html", ".htm"])
_register("xml", "XML Belgesi", "document", "application/xml", [".xml"])
_register("json", "JSON Verisi", "document", "application/json", [".json"])
_register("yaml", "YAML Verisi", "document", "application/yaml", [".yaml", ".yml"])
_register("csv", "CSV Tablosu", "document", "text/csv", [".csv"])
_register("tsv", "TSV Tablosu", "document", "text/tab-separated-values", [".tsv"])
_register("doc", "Eski Word Belgesi (DOC)", "document", "application/msword", [".doc"], legacy=True)

# Tablolar
_register("xlsx", "Excel Çalışma Kitabı", "spreadsheet", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", [".xlsx"])
_register("xlsm", "Excel Çalışma Kitabı (Makrolu)", "spreadsheet", "application/vnd.ms-excel.sheet.macroEnabled.12", [".xlsm"], macro_enabled=True)
_register("ods", "OpenDocument Tablo", "spreadsheet", "application/vnd.oasis.opendocument.spreadsheet", [".ods"])
_register("xls", "Eski Excel (XLS)", "spreadsheet", "application/vnd.ms-excel", [".xls"], legacy=True)

# Sunumlar
_register("pptx", "PowerPoint Sunumu", "presentation", "application/vnd.openxmlformats-officedocument.presentationml.presentation", [".pptx"])
_register("pptm", "PowerPoint Sunumu (Makrolu)", "presentation", "application/vnd.ms-powerpoint.presentation.macroEnabled.12", [".pptm"], macro_enabled=True)
_register("odp", "OpenDocument Sunum", "presentation", "application/vnd.oasis.opendocument.presentation", [".odp"])
_register("ppt", "Eski PowerPoint (PPT)", "presentation", "application/vnd.ms-powerpoint", [".ppt"], legacy=True)

# Görseller
_register("png", "PNG Görsel", "image", "image/png", [".png"], text_capable=False)
_register("jpeg", "JPEG Görsel", "image", "image/jpeg", [".jpg", ".jpeg"], text_capable=False)
_register("gif", "GIF Görsel", "image", "image/gif", [".gif"], text_capable=False)
_register("webp", "WebP Görsel", "image", "image/webp", [".webp"], text_capable=False)
_register("bmp", "BMP Görsel", "image", "image/bmp", [".bmp"], text_capable=False)
_register("tiff", "TIFF Görsel", "image", "image/tiff", [".tif", ".tiff"], text_capable=False)
_register("ico", "Simge (ICO)", "image", "image/x-icon", [".ico"], text_capable=False)
_register("avif", "AVIF Görsel", "image", "image/avif", [".avif"], text_capable=False)
_register("heic", "HEIC Görsel", "image", "image/heic", [".heic"], text_capable=False)
_register("svg", "SVG Görsel", "image", "image/svg+xml", [".svg"], text_capable=True)

# Ses
_register("mp3", "MP3 Ses", "audio", "audio/mpeg", [".mp3"], text_capable=False)
_register("wav", "WAV Ses", "audio", "audio/wav", [".wav"], text_capable=False)
_register("flac", "FLAC Ses", "audio", "audio/flac", [".flac"], text_capable=False)
_register("ogg", "OGG Ses", "audio", "audio/ogg", [".ogg"], text_capable=False)
_register("opus", "Opus Ses", "audio", "audio/opus", [".opus"], text_capable=False)
_register("m4a", "M4A Ses", "audio", "audio/mp4", [".m4a"], text_capable=False)
_register("aac", "AAC Ses", "audio", "audio/aac", [".aac"], text_capable=False)
_register("wma", "WMA Ses", "audio", "audio/x-ms-wma", [".wma"], text_capable=False)

# Video
_register("mp4", "MP4 Video", "video", "video/mp4", [".mp4"], text_capable=False)
_register("mov", "QuickTime Video", "video", "video/quicktime", [".mov"], text_capable=False)
_register("mkv", "Matroska Video", "video", "video/x-matroska", [".mkv"], text_capable=False)
_register("webm", "WebM Video", "video", "video/webm", [".webm"], text_capable=False)
_register("avi", "AVI Video", "video", "video/x-msvideo", [".avi"], text_capable=False)
_register("m4v", "M4V Video", "video", "video/x-m4v", [".m4v"], text_capable=False)
_register("mpg", "MPEG Video", "video", "video/mpeg", [".mpg", ".mpeg"], text_capable=False)
_register("wmv", "WMV Video", "video", "video/x-ms-wmv", [".wmv"], text_capable=False)
_register("flv", "FLV Video", "video", "video/x-flv", [".flv"], text_capable=False)

# Kod
CODE_EXTENSIONS = [
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".kts", ".sql", ".sh", ".bash",
    ".ps1", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".dart", ".lua", ".r",
    ".pl", ".scala", ".clj", ".ex", ".exs", ".sol", ".asm", ".ini", ".toml", ".cfg",
]
_register("code", "Kaynak Kod", "code", "text/plain", CODE_EXTENSIONS)

# Arşivler
_register("zip", "ZIP Arşivi", "archive", "application/zip", [".zip"], text_capable=False)
_register("tar", "TAR Arşivi", "archive", "application/x-tar", [".tar"], text_capable=False)
_register("gz", "GZIP Arşivi", "archive", "application/gzip", [".gz"], text_capable=False)
_register("tgz", "TGZ Arşivi", "archive", "application/gzip", [".tgz"], text_capable=False)
_register("bz2", "BZIP2 Arşivi", "archive", "application/x-bzip2", [".bz2", ".tbz2"], text_capable=False)
_register("xz", "XZ Arşivi", "archive", "application/x-xz", [".xz", ".txz"], text_capable=False)
_register("rar", "RAR Arşivi", "archive", "application/vnd.rar", [".rar"], text_capable=False)
_register("7z", "7-Zip Arşivi", "archive", "application/x-7z-compressed", [".7z"], text_capable=False)
_register("apk", "Android Paketi (APK)", "archive", "application/vnd.android.package-archive", [".apk"], text_capable=False)
_register("jar", "Java Arşivi (JAR)", "archive", "application/java-archive", [".jar"], text_capable=False)

# Çalıştırılabilirler
_register("exe", "Windows Uygulaması", "executable", "application/vnd.microsoft.portable-executable", [".exe", ".dll", ".com", ".scr", ".sys"], text_capable=False)
_register("msi", "Windows Yükleyici", "executable", "application/x-msi", [".msi"], text_capable=False)
_register("script", "Çalıştırılabilir Betik", "executable", "text/plain", [".bat", ".cmd", ".vbs", ".wsf", ".hta"])
_register("elf", "Linux/Unix Çalıştırılabilir", "executable", "application/x-executable", [], text_capable=False)
_register("macho", "macOS Çalıştırılabilir", "executable", "application/x-mach-binary", [], text_capable=False)

_register("unknown", "Bilinmeyen Dosya", "unknown", "application/octet-stream", [], text_capable=False)

EXTENSION_MAP: Dict[str, str] = {}
for _info in FORMATS.values():
    for _ext in _info.extensions:
        EXTENSION_MAP[_ext] = _info.key

_ALIASES = {
    ".jpe": "jpeg", ".jfif": "jpeg", ".tif": "tiff", ".htm": "html", ".yml": "yaml",
    ".markdown": "md", ".text": "txt", ".log": "txt", ".tbz": "bz2", ".txz": "xz",
    ".mpeg": "mpg", ".mpe": "mpg", ".qt": "mov", ".wave": "wav",
}
for _ext, _fmt in _ALIASES.items():
    EXTENSION_MAP[_ext] = _fmt

_COMPATIBLE = [
    {"jpeg"}, {"tiff"}, {"html"}, {"yaml", "md", "txt"}, {"mpg"}, {"wav"},
    {"code", "txt"}, {"gz", "tgz"}, {"bz2"}, {"xz", "tgz"},
]

TEXT_FORMATS = {"txt", "md", "html", "xml", "json", "yaml", "csv", "tsv", "code", "svg"}


@dataclass
class Detection:
    format: str
    category: str
    mime: str
    label: str
    confidence: str
    extension: str
    extension_mismatch: bool = False
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, object] = field(default_factory=dict)
    legacy: bool = False
    macro_enabled: bool = False
    executable: bool = False
    text_capable: bool = True

    def as_dict(self) -> dict:
        return {
            "format": self.format,
            "category": self.category,
            "category_label": CATEGORY_LABELS_TR.get(self.category, self.category),
            "mime": self.mime,
            "label": self.label,
            "confidence": self.confidence,
            "extension": self.extension,
            "extension_mismatch": self.extension_mismatch,
            "legacy": self.legacy,
            "macro_enabled": self.macro_enabled,
            "executable": self.executable,
            "warnings": list(self.warnings),
        }


# ------------------------------------------------------------
# SİHİRLİ BAYT ALGILAMA
# ------------------------------------------------------------

def _zip_descriptor(data: bytes) -> Tuple[str, Dict[str, object], List[str]]:
    warnings: List[str] = []
    details: Dict[str, object] = {}
    try:
        zf = open_safe_zip(data)
    except FileAnalysisError as exc:
        return "zip", {"zip_validation_error": exc.code}, warnings

    with zf:
        names = zf.namelist()
        lower = {n.lower() for n in names}
        details["zip_entries"] = len(names)
        has_macros = any(n.endswith("vbaproject.bin") for n in lower)
        if has_macros:
            details["has_macros"] = True

        if "mimetype" in lower:
            try:
                mt = safe_zip_read(zf, "mimetype", 512).decode("ascii", errors="ignore").strip().lower()
            except FileAnalysisError:
                mt = ""
            if mt == "application/epub+zip":
                return "epub", details, warnings
            if mt == "application/vnd.oasis.opendocument.text":
                return "odt", details, warnings
            if mt == "application/vnd.oasis.opendocument.spreadsheet":
                return "ods", details, warnings
            if mt == "application/vnd.oasis.opendocument.presentation":
                return "odp", details, warnings

        if "meta-inf/container.xml" in lower or any(n.endswith(".opf") for n in lower):
            return "epub", details, warnings

        if "androidmanifest.xml" in lower:
            return "apk", details, warnings
        if "meta-inf/manifest.mf" in lower and any(n.endswith(".class") for n in lower):
            return "jar", details, warnings

        if "word/document.xml" in lower:
            return ("docm" if has_macros else "docx"), details, warnings
        if "xl/workbook.xml" in lower:
            return ("xlsm" if has_macros else "xlsx"), details, warnings
        if "ppt/presentation.xml" in lower:
            return ("pptm" if has_macros else "pptx"), details, warnings

        try:
            ct = safe_zip_read(zf, "[Content_Types].xml", 512 * 1024).decode("utf-8", errors="ignore")
            if "macroEnabled" in ct or "vbaProject" in ct:
                details["has_macros"] = True
                if "wordprocessingml" in ct:
                    return "docm", details, warnings
                if "spreadsheetml" in ct:
                    return "xlsm", details, warnings
                if "presentationml" in ct:
                    return "pptm", details, warnings
        except FileAnalysisError:
            pass

        if has_macros:
            warnings.append("Arşiv içinde VBA makro bileşeni tespit edildi.")
        return "zip", details, warnings


def detect_binary_format(data: bytes) -> Tuple[Optional[str], Dict[str, object], List[str]]:
    """Sihirli baytlardan format tahmini. Dönen: (format | None, detaylar, uyarılar)."""
    if not data:
        return None, {}, []
    head = data[:512]
    warnings: List[str] = []
    details: Dict[str, object] = {}

    if head.startswith(b"%PDF-"):
        return "pdf", details, warnings
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return _zip_descriptor(data)
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole", details, warnings
    if head.startswith(b"{\\rtf"):
        return "rtf", details, warnings
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", details, warnings
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg", details, warnings
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif", details, warnings
    if head.startswith(b"BM") and len(head) > 14:
        return "bmp", details, warnings
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff", details, warnings
    if head.startswith(b"RIFF") and len(head) >= 12:
        kind = head[8:12]
        if kind == b"WEBP":
            return "webp", details, warnings
        if kind == b"WAVE":
            return "wav", details, warnings
        if kind == b"AVI ":
            return "avi", details, warnings
    if head.startswith(b"\x00\x00\x01\x00"):
        return "ico", details, warnings
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12].lower()
        details["brand"] = brand.decode("latin-1", errors="ignore")
        if brand in (b"avif", b"avis"):
            return "avif", details, warnings
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
            return "heic", details, warnings
        if brand in (b"m4a ", b"m4b ", b"m4p "):
            return "m4a", details, warnings
        if brand == b"qt  ":
            return "mov", details, warnings
        return "mp4", details, warnings
    if head.startswith(b"\x1aE\xdf\xa3"):
        if b"webm" in data[:4096].lower():
            return "webm", details, warnings
        return "mkv", details, warnings
    if head.startswith(b"fLaC"):
        return "flac", details, warnings
    if head.startswith(b"OggS"):
        if b"OpusHead" in data[:256]:
            return "opus", details, warnings
        return "ogg", details, warnings
    if head.startswith(b"ID3"):
        return "mp3", details, warnings
    if len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        if (head[1] & 0x06) == 0 and (head[1] & 0xF0) == 0xF0:
            return "aac", details, warnings
        return "mp3", details, warnings
    if head.startswith(b"\x30\x26\xb2\x75\x8e\x66\xcf\x11"):
        return ("wma" if b"ASF" in head else "wmv"), details, warnings
    if head.startswith(b"FLV"):
        return "flv", details, warnings
    if head.startswith((b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3")):
        return "mpg", details, warnings
    if head.startswith(b"Rar!\x1a\x07"):
        return "rar", details, warnings
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z", details, warnings
    if head.startswith(b"\x1f\x8b"):
        return "gz", details, warnings
    if head.startswith(b"BZh"):
        return "bz2", details, warnings
    if head.startswith(b"\xfd7zXZ\x00"):
        return "xz", details, warnings
    if len(data) > 262 and data[257:262] == b"ustar":
        return "tar", details, warnings
    if head.startswith(b"MZ"):
        return "exe", details, warnings
    if head.startswith(b"\x7fELF"):
        return "elf", details, warnings
    if head.startswith((b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe")):
        return "macho", details, warnings

    return None, details, warnings


# ------------------------------------------------------------
# METİN İÇERİK SEZGİSİ
# ------------------------------------------------------------

def _looks_like_csv(text: str) -> Optional[str]:
    lines = [ln for ln in text.splitlines()[:8] if ln.strip()]
    if len(lines) < 2:
        return None
    for delimiter, fmt in (("\t", "tsv"), (",", "csv"), (";", "csv")):
        counts = [ln.count(delimiter) for ln in lines]
        if min(counts) >= 1 and len(set(counts)) <= 2:
            return fmt
    return None


def sniff_text_format(data: bytes) -> Tuple[Optional[str], Dict[str, object]]:
    if looks_binary(data):
        return None, {}

    sample_bytes = data[:262_144]
    text, encoding = decode_text(sample_bytes)
    details: Dict[str, object] = {"encoding": encoding}
    stripped = text.lstrip("\ufeff \t\r\n")

    if not stripped:
        return "txt", details

    if stripped[:1] in "{[":
        try:
            json.loads(text if len(data) <= len(sample_bytes) else stripped)
            return "json", details
        except (json.JSONDecodeError, ValueError):
            pass

    if re.match(r"(?is)^<!doctype\s+html\b|^<html\b", stripped):
        return "html", details
    if re.search(r"(?is)<svg[\s>]", stripped[:4096]):
        return "svg", details
    if stripped.startswith("<?xml") or re.match(r"(?s)^<[A-Za-z_][\w:.-]*(\s|/?>)", stripped):
        return "xml", details
    if re.match(r"(?m)^---\s*$", stripped) and re.search(r"(?m)^[\w.-]+\s*:\s*\S", stripped):
        return "yaml", details

    csv_kind = _looks_like_csv(stripped)
    if csv_kind:
        return csv_kind, details

    code_markers = (
        "def ", "class ", "import ", "from ", "function ", "const ", "let ", "var ",
        "#include", "public static", "package ", "fn ", "func ", "use ", "<?php",
        "SELECT ", "CREATE TABLE", "=>", "];",
    )
    if sum(1 for marker in code_markers if marker in stripped[:8192]) >= 2:
        return "code", details

    return "txt", details


# ------------------------------------------------------------
# ANA ALGILAMA
# ------------------------------------------------------------

def _extension_of(filename: str) -> str:
    name = (filename or "").lower().strip()
    idx = name.rfind(".")
    return name[idx:] if idx > 0 else ""


def _mime_equivalent(declared: str, detected: str) -> bool:
    declared = (declared or "").split(";")[0].strip().lower()
    if not declared or declared in ("application/octet-stream", "*/*"):
        return True
    if declared == detected:
        return True
    aliases = {
        "image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg",
        "text/xml": "application/xml", "application/x-yaml": "application/yaml",
        "text/yaml": "application/yaml", "application/vnd.ms-word": "application/msword",
        "text/x-python": "text/plain", "application/javascript": "text/plain",
        "text/javascript": "text/plain", "application/x-zip-compressed": "application/zip",
        "application/vnd.oasis.opendocument.text": "application/vnd.oasis.opendocument.text",
    }
    return aliases.get(declared, declared) == aliases.get(detected, detected)


def _is_compatible(ext_format: str, detected_format: str) -> bool:
    if ext_format == detected_format:
        return True
    return any(ext_format in group and detected_format in group for group in _COMPATIBLE)


def _resolve_ole(ext_format: Optional[str]) -> str:
    if ext_format in ("doc", "xls", "ppt"):
        return ext_format
    if ext_format in ("xlsx", "xlsm"):
        return "xls"
    if ext_format in ("pptx", "pptm"):
        return "ppt"
    return "doc"


def detect_file(filename: str, data: bytes, declared_mime: Optional[str] = None) -> Detection:
    ext = _extension_of(filename)
    ext_format = EXTENSION_MAP.get(ext)
    binary_format, details, warnings = detect_binary_format(data)
    details = dict(details)
    warnings = list(warnings)

    if ext_format is None and binary_format is None and not data.strip():
        raise FileAnalysisError("Boş dosya analiz edilemez.", code="empty_file")

    detected_format = binary_format
    if detected_format == "ole":
        detected_format = _resolve_ole(ext_format)
        details["ole_legacy"] = True

    if detected_format is None:
        sniffed, sniff_details = sniff_text_format(data)
        details.update(sniff_details)
        if sniffed:
            detected_format = sniffed

    # Uzantı .json ise içerik metin olarak algılansa bile JSON olarak doğrulanır.
    # Böylece bozuk/eksik JSON sessizce düz metin sayılmaz; net Türkçe hata döner.
    if ext_format == "json" and detected_format in TEXT_FORMATS and detected_format != "json":
        details["declared_json"] = True
        detected_format = "json"

    if detected_format is None or detected_format not in FORMATS:
        info = FORMATS["unknown"]
        return Detection(
            format="unknown", category="unknown", mime=info.mime, label=info.label,
            confidence="low", extension=ext, warnings=warnings + ["Dosya türü belirlenemedi."],
            details=details,
        )

    info = FORMATS[detected_format]
    mismatch = False
    confidence = "medium"

    if ext_format:
        if ext_format == detected_format or _is_compatible(ext_format, detected_format):
            confidence = "high"
        else:
            mismatch = True
            confidence = "medium"
            ext_info = FORMATS.get(ext_format)
            warnings.append(
                f"Uzantı içerikle uyuşmuyor: dosya adı '{ext}' ({ext_info.label if ext_info else ext_format}) "
                f"ancak içerik {info.label} olarak algılandı."
            )
    else:
        if ext:
            warnings.append(f"Tanınmayan uzantı ({ext}); tür içerikten algılandı.")
        confidence = "low" if detected_format in TEXT_FORMATS else "medium"

    if ext_format in TEXT_FORMATS and detected_format in TEXT_FORMATS and ext_format != detected_format:
        if not _is_compatible(ext_format, detected_format):
            mismatch = True
            warnings.append(
                f"Metin içeriği beklenenden farklı: uzantı '{ext}', algılanan içerik {info.label}."
            )

    if declared_mime and not _mime_equivalent(declared_mime, info.mime):
        warnings.append(
            f"Bildirilen MIME türü ({declared_mime}) algılanan türle ({info.mime}) uyuşmuyor."
        )

    if info.legacy:
        warnings.append(
            "Eski ikili Office biçimi algılandı. Güvenli metin çıkarımı için DOCX/XLSX/PPTX'e dönüştürün."
        )
    if info.macro_enabled or details.get("has_macros"):
        warnings.append("Makro içeren Office dosyası: güvenlik nedeniyle analiz reddedilecek.")

    return Detection(
        format=info.key,
        category=info.category,
        mime=info.mime,
        label=info.label,
        confidence=confidence,
        extension=ext,
        extension_mismatch=mismatch,
        warnings=warnings,
        details=details,
        legacy=info.legacy,
        macro_enabled=info.macro_enabled or bool(details.get("has_macros")),
        executable=info.category == "executable",
        text_capable=info.text_capable,
    )


def supported_formats() -> Dict[str, object]:
    groups: Dict[str, List[dict]] = {}
    for info in FORMATS.values():
        if info.key == "unknown":
            continue
        groups.setdefault(info.category, []).append({
            "key": info.key,
            "label": info.label,
            "mime": info.mime,
            "extensions": [e.lstrip(".") for e in info.extensions],
        })
    return {
        "categories": [
            {"key": key, "label": CATEGORY_LABELS_TR.get(key, key), "formats": sorted(items, key=lambda x: x["key"])}
            for key, items in sorted(groups.items())
        ],
        "unsupported_note": (
            "Eski DOC/XLS/PPT, şifreli arşivler ve makro içeren Office dosyaları güvenlik nedeniyle desteklenmez."
        ),
    }
