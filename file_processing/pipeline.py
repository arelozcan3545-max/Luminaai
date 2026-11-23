# ============================================================
# LUMINA AI - DOSYA ANALİZ HATTI (PIPELINE)
# Algıla → güvenlik denetle → zaman aşımlı ayrıştır → raporla.
# Yüklenen hiçbir dosya çalıştırılmaz; geçici dosya oluşturulmaz.
# ============================================================

import logging
from typing import Optional

from .security import (
    FileAnalysisError,
    MAX_UPLOAD_BYTES,
    MAX_TEXT_CHARS,
    normalize_filename,
    open_safe_zip,
    scan_zip_macros,
    run_with_timeout,
    PARSE_TIMEOUT_SECS,
)
from .detector import (
    detect_file,
    supported_formats,
    Detection,
    CATEGORY_LABELS_TR,
    FORMATS,
)
from .adapters import extract_content

logger = logging.getLogger("LuminaFilePipeline")

ZIP_BASED_FORMATS = {
    "docx", "docm", "xlsx", "xlsm", "pptx", "pptm",
    "odt", "ods", "odp", "epub", "zip", "apk", "jar",
}

PREVIEW_CHARS = 3_000
EXCERPT_CHARS = 4_000


OFFICE_OOXML_FORMATS = {"docx", "docm", "xlsx", "xlsm", "pptx", "pptm", "odt", "ods", "odp"}


def _validate_zip_based(data: bytes, detection: Detection) -> None:
    """Zip tabanlı dosyalarda bomb/path traversal ve Office makro denetimi."""
    if detection.format not in ZIP_BASED_FORMATS:
        return
    with open_safe_zip(data) as zf:
        has_macros = scan_zip_macros(zf)
    if has_macros and detection.format in OFFICE_OOXML_FORMATS:
        raise FileAnalysisError(
            "Dosya VBA makrosu içeriyor. Güvenlik nedeniyle makrolu Office dosyaları analiz edilmez. "
            "Lütfen makroları kaldırıp yeniden yükleyin.",
            code="macro_document", status_code=422,
        )


def _build_preview(text: str, detection: Detection) -> str:
    if text:
        return text[:PREVIEW_CHARS]
    return f"{detection.label} analiz edildi ancak okunabilir metin bulunamadı."


def analyze_file(
    filename: Optional[str],
    data: bytes,
    declared_mime: Optional[str] = None,
) -> dict:
    """Yüklenen dosyayı güvenli biçimde analiz eder ve yapılandırılmış rapor döner."""
    safe_name = normalize_filename(filename)

    if not data:
        raise FileAnalysisError("Boş dosya analiz edilemez.", code="empty_file")

    if len(data) > MAX_UPLOAD_BYTES:
        raise FileAnalysisError(
            f"Dosya boyutu çok büyük. Azami {MAX_UPLOAD_BYTES // (1024 * 1024)} MB yükleyebilirsiniz.",
            code="file_too_large", status_code=413,
        )

    detection = detect_file(safe_name, data, declared_mime)

    if detection.executable:
        raise FileAnalysisError(
            "Çalıştırılabilir dosyalar (EXE/DLL/MSI/betik) güvenlik nedeniyle kabul edilmez. "
            "Yüklenen dosyalar hiçbir koşulda çalıştırılmaz.",
            code="executable_rejected", status_code=415,
        )

    if detection.format == "unknown":
        raise FileAnalysisError(
            "Desteklenmeyen veya tanınmayan dosya biçimi. Desteklenen biçimler için "
            "'/api/v1/files/formats' uç noktasını inceleyebilirsiniz.",
            code="unsupported_format", status_code=415,
        )

    _validate_zip_based(data, detection)

    if detection.macro_enabled:
        raise FileAnalysisError(
            "Makro içeren Office dosyaları güvenlik nedeniyle analiz edilmez.",
            code="macro_document", status_code=422,
        )

    try:
        extracted = run_with_timeout(
            lambda: extract_content(detection, data),
            timeout=PARSE_TIMEOUT_SECS,
        )
    except FileAnalysisError:
        raise
    except MemoryError as exc:
        raise FileAnalysisError(
            "Dosya işlenirken bellek sınırı aşıldı; daha küçük bir dosya deneyin.",
            code="out_of_memory", status_code=422,
        ) from exc
    except Exception as exc:  # pragma: no cover - savunma amaçlı
        logger.exception("Dosya ayrıştırma hatası: %s", safe_name)
        raise FileAnalysisError(
            f"Dosya analiz edilirken beklenmeyen bir hata oluştu: {str(exc)[:160]}",
            code="parse_failed", status_code=422,
        ) from exc

    text = (extracted.text or "").strip()[:MAX_TEXT_CHARS]
    warnings = list(detection.warnings) + list(extracted.warnings)

    if not text and detection.category in ("document", "spreadsheet", "presentation", "code"):
        if detection.format == "pdf":
            warnings.append("PDF'ten metin çıkarılamadı; belge taranmış olabilir.")
        else:
            raise FileAnalysisError(
                "Dosyada okunabilir metin bulunamadı. Belge boş, taranmış veya desteklenmeyen bir yapıda olabilir.",
                code="no_readable_text", status_code=422,
            )

    if len(text) >= MAX_TEXT_CHARS:
        warnings.append(f"Metin {MAX_TEXT_CHARS} karakterle sınırlandırıldı.")

    preview = _build_preview(text, detection)
    excerpt = text[:EXCERPT_CHARS] if text else preview[:EXCERPT_CHARS]

    warnings = list(dict.fromkeys(warnings))
    format_info = detection.as_dict()
    format_info["warnings"] = warnings

    return {
        "success": True,
        "filename": safe_name,
        "filetype": detection.format,
        "format": detection.format,
        "category": detection.category,
        "category_label": CATEGORY_LABELS_TR.get(detection.category, detection.category),
        "mime": detection.mime,
        "confidence": detection.confidence,
        "extension_mismatch": detection.extension_mismatch,
        "characters": len(text),
        "preview": preview,
        "excerpt": excerpt,
        "metadata": extracted.metadata,
        "warnings": warnings,
        "detected": format_info,
        "limits": {
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "max_text_chars": MAX_TEXT_CHARS,
            "parse_timeout_seconds": PARSE_TIMEOUT_SECS,
        },
        "security": {
            "executed": False,
            "temporary_files_created": False,
            "archive_scanned": detection.format in ZIP_BASED_FORMATS or detection.category == "archive",
            "macro_executed": False,
        },
    }


__all__ = [
    "analyze_file",
    "detect_file",
    "supported_formats",
    "FileAnalysisError",
    "MAX_UPLOAD_BYTES",
    "FORMATS",
]
