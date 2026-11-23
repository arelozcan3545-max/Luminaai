# ============================================================
# LUMINA AI - DOSYA İÇERİK ADAPTÖRLERİ
# Her format için güvenli, sınırlı ve çalıştırmasız içerik çıkarımı.
# Hiçbir dosya çalıştırılmaz; makrolar/etkin içerik yok sayılır.
# ============================================================

import io
import re
import csv
import json
import gzip
import bz2
import lzma
import tarfile
import zipfile
import struct
from dataclasses import dataclass, field
from html import unescape
from typing import Dict, List, Optional, Tuple

from .detector import Detection, FORMATS
from .security import (
    FileAnalysisError,
    MAX_TEXT_CHARS,
    open_safe_zip,
    safe_zip_read,
    html_to_text,
    strip_markup,
    decode_text,
    clean_text,
    validate_tar,
    describe_gzip,
)

# Opsiyonel bağımlılıklar
try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:  # pragma: no cover
    HAS_PYPDF = False

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:  # pragma: no cover
    HAS_OPENPYXL = False

try:
    import yaml
    HAS_YAML = True
except ImportError:  # pragma: no cover
    HAS_YAML = False

try:
    from PIL import Image, UnidentifiedImageError
    Image.MAX_IMAGE_PIXELS = 40_000_000
    HAS_PIL = True
except ImportError:  # pragma: no cover
    HAS_PIL = False

try:
    from defusedxml import ElementTree as SafeET
    HAS_DEFUSEDXML = True
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as SafeET
    HAS_DEFUSEDXML = False


@dataclass
class ExtractedContent:
    text: str = ""
    metadata: Dict[str, object] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def _safe_xml(text: str):
    return SafeET.fromstring(text)


def _core_props(zf: zipfile.ZipFile) -> Dict[str, str]:
    props: Dict[str, str] = {}
    try:
        raw = safe_zip_read(zf, "docProps/core.xml", 512 * 1024).decode("utf-8", errors="ignore")
        for tag in ("title", "creator", "subject", "description", "lastModifiedBy"):
            m = re.search(rf"<[^>]*:{tag}[^>]*>(.*?)</[^>]*:{tag}>", raw, re.IGNORECASE | re.DOTALL)
            if m:
                props[tag] = unescape(m.group(1)).strip()[:300]
    except FileAnalysisError:
        pass
    return props


# ------------------------------------------------------------
# METİN / YAPISAL BELGELER
# ------------------------------------------------------------

def extract_plain_text(data: bytes, detection: Detection) -> ExtractedContent:
    text, encoding = decode_text(data)
    return ExtractedContent(
        text=clean_text(text),
        metadata={"encoding": encoding},
    )


def extract_markdown(data: bytes) -> ExtractedContent:
    text, encoding = decode_text(data)
    return ExtractedContent(
        text=clean_text(text),
        metadata={
            "encoding": encoding,
            "headings": len(re.findall(r"(?m)^#{1,6}\s+", text)),
            "code_blocks": text.count("```") // 2,
        },
    )


def extract_json(data: bytes) -> ExtractedContent:
    text, encoding = decode_text(data)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise FileAnalysisError(
            f"Geçersiz JSON: satır {getattr(exc, 'lineno', '?')}, sütun {getattr(exc, 'colno', '?')}.",
            code="invalid_json", status_code=422,
        ) from exc
    metadata = {
        "encoding": encoding,
        "root_type": type(parsed).__name__,
        "top_level_keys": len(parsed) if isinstance(parsed, (dict, list)) else 0,
    }
    pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
    return ExtractedContent(text=clean_text(pretty), metadata=metadata)


def extract_yaml(data: bytes) -> ExtractedContent:
    if not HAS_YAML:
        raise FileAnalysisError("YAML desteği sunucuda kurulu değil (PyYAML).", code="missing_dependency", status_code=503)
    if len(data) > 2 * 1024 * 1024:
        raise FileAnalysisError("YAML dosyası güvenli ayrıştırma sınırından büyük (2 MB).", code="yaml_too_large", status_code=422)
    text, encoding = decode_text(data)
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        raise FileAnalysisError(f"Geçersiz YAML: {str(exc)[:200]}", code="invalid_yaml", status_code=422) from exc
    except (RecursionError, MemoryError) as exc:
        raise FileAnalysisError("YAML içeriği güvenli sınırlar içinde ayrıştırılamadı.", code="yaml_too_complex", status_code=422) from exc
    return ExtractedContent(
        text=clean_text(text),
        metadata={"encoding": encoding, "document_count": len(docs)},
        warnings=["YAML içindeki etiketler/nesneler çalıştırılmadı; yalnızca veri olarak okundu."],
    )


def extract_csv(data: bytes, delimiter: str = ",") -> ExtractedContent:
    text, encoding = decode_text(data)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        pass

    rows: List[List[str]] = []
    max_cols = 0
    truncated = False
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    for idx, row in enumerate(reader):
        if idx >= 2000:
            truncated = True
            break
        cells = [str(c).strip()[:500] for c in row[:50]]
        max_cols = max(max_cols, len(cells))
        rows.append(cells)
    body = "\n".join("\t".join(r) for r in rows)
    warnings = ["Dosya ilk 2000 satırla sınırlandırıldı."] if truncated else []
    return ExtractedContent(
        text=clean_text(body),
        metadata={
            "encoding": encoding,
            "delimiter": delimiter,
            "row_count": len(rows),
            "column_count": max_cols,
            "truncated": truncated,
        },
        warnings=warnings,
    )


def extract_rtf(data: bytes) -> ExtractedContent:
    text, encoding = decode_text(data)
    original_len = len(text)
    # Hedef grupları ve resim/nesne bloklarını kaldır
    text = re.sub(r"\{\\\*[\s\S]*?\}", " ", text)
    text = re.sub(r"\{\\(?:pict|object|objdata|fonttbl|colortbl|stylesheet|info)[\s\S]*?\}", " ", text)
    text = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1254", errors="ignore"), text)
    text = text.replace("\\par", "\n").replace("\\line", "\n").replace("\\tab", "\t")
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
    text = text.replace("\\\\", "\\").replace("\\{", "{").replace("\\}", "}")
    text = text.replace("{", "").replace("}", "")
    return ExtractedContent(
        text=clean_text(unescape(text)),
        metadata={"encoding": encoding, "source_characters": original_len},
    )


def extract_html(data: bytes) -> ExtractedContent:
    text_raw, encoding = decode_text(data)
    body, title = html_to_text(text_raw)
    warnings = []
    if re.search(r"(?is)<\s*(script|iframe|object|embed)\b", text_raw):
        warnings.append("HTML içindeki betik/etkin içerik çalıştırılmadı; yalnızca metin çıkarıldı.")
    return ExtractedContent(
        text=body,
        metadata={"encoding": encoding, "title": title, "links": len(re.findall(r"(?i)<a\s", text_raw))},
        warnings=warnings,
    )


def extract_xml(data: bytes) -> ExtractedContent:
    text_raw, encoding = decode_text(data)
    root = None
    m = re.search(r"<\s*([A-Za-z_][\w:.-]*)", re.sub(r"<\?[\s\S]*?\?>", "", text_raw))
    if m:
        root = m.group(1)
    warnings = ["XML varlıkları (entity) genişletilmedi; dış kaynaklar yüklenmedi."]
    return ExtractedContent(
        text=strip_markup(text_raw),
        metadata={"encoding": encoding, "root_element": root},
        warnings=warnings,
    )


def extract_svg(data: bytes) -> ExtractedContent:
    text_raw, encoding = decode_text(data)
    body = strip_markup(text_raw)
    width = re.search(r'\bwidth=["\']([^"\']+)', text_raw)
    height = re.search(r'\bheight=["\']([^"\']+)', text_raw)
    return ExtractedContent(
        text=body,
        metadata={
            "encoding": encoding,
            "width": width.group(1) if width else None,
            "height": height.group(1) if height else None,
        },
        warnings=["SVG etkin içerik (script/foreignObject) çalıştırılmadı; yalnızca metin çıkarıldı."],
    )


# ------------------------------------------------------------
# OFFICE / ODF / EPUB
# ------------------------------------------------------------

def _extract_docx(data: bytes) -> ExtractedContent:
    zf = open_safe_zip(data)
    with zf:
        xml_bytes = safe_zip_read(zf, "word/document.xml", 20 * 1024 * 1024)
        xml_text = xml_bytes.decode("utf-8", errors="ignore")
        paragraphs: List[str] = []
        for para in re.split(r"</w:p>", xml_text):
            para = re.sub(r"<w:tab[^>]*/>", "\t", para)
            para = re.sub(r"<w:br[^>]*/>", "\n", para)
            pieces = re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, re.DOTALL)
            if pieces:
                paragraphs.append(unescape("".join(pieces)))
        props = _core_props(zf)
        has_macros = any(n.lower().endswith("vbaproject.bin") for n in zf.namelist())
        metadata = {
            "paragraph_count": len(paragraphs),
            "title": props.get("title"),
            "author": props.get("creator"),
        }
    warnings = ["DOCX içindeki etkin nesneler çalıştırılmadı."]
    if has_macros:
        warnings.append("Belge içinde VBA makro bileşeni bulundu; çalıştırılmadı.")
    return ExtractedContent(
        text=clean_text("\n".join(paragraphs)),
        metadata=metadata,
        warnings=warnings,
    )


def _extract_odf(data: bytes, kind: str) -> ExtractedContent:
    zf = open_safe_zip(data)
    with zf:
        content = safe_zip_read(zf, "content.xml", 30 * 1024 * 1024).decode("utf-8", errors="ignore")
        props = _core_props(zf)
        meta_raw = ""
        if "meta.xml" in zf.namelist():
            try:
                meta_raw = safe_zip_read(zf, "meta.xml", 512 * 1024).decode("utf-8", errors="ignore")
            except FileAnalysisError:
                pass

    metadata: Dict[str, object] = {
        "title": props.get("title"),
        "author": props.get("creator"),
    }
    if meta_raw:
        m = re.search(r"<meta:generator[^>]*>(.*?)</meta:generator>", meta_raw, re.DOTALL)
        if m:
            metadata["generator"] = unescape(m.group(1)).strip()[:200]

    if kind == "ods":
        rows: List[str] = []
        max_cols = 0
        for raw_row in re.split(r"</table:table-row>", content)[:2000]:
            cells: List[str] = []
            for cell in re.split(r"</table:table-cell>", raw_row)[:50]:
                texts = re.findall(r"<text:p[^>]*>(.*?)</text:p>", cell, re.DOTALL)
                cell_text = " ".join(unescape(strip_markup(t)) for t in texts).strip()
                repeat = re.search(r'table:number-columns-repeated="(\d+)"', cell)
                times = min(20, int(repeat.group(1))) if repeat else 1
                cells.extend([cell_text] * times)
            if any(c for c in cells):
                max_cols = max(max_cols, len(cells))
                rows.append("\t".join(cells[:50]))
        text = "\n".join(rows)
        metadata.update({"row_count": len(rows), "column_count": max_cols})
    else:
        body = re.sub(r"</(?:text:p|text:h|text:list-item)>", "\n", content)
        body = re.sub(r"<text:(?:tab|line-break)[^>]*/>", "\t", body)
        text = strip_markup(body)
        metadata["paragraph_count"] = text.count("\n") + 1 if text else 0

    return ExtractedContent(
        text=clean_text(text),
        metadata=metadata,
        warnings=["OpenDocument içindeki makrolar/etkin nesneler çalıştırılmadı."],
    )


def _extract_pptx(data: bytes) -> ExtractedContent:
    zf = open_safe_zip(data)
    slide_names: List[Tuple[int, str]] = []
    with zf:
        for name in zf.namelist():
            m = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
            if m:
                slide_names.append((int(m.group(1)), name))
        slide_names.sort()
        parts: List[str] = []
        for idx, (number, name) in enumerate(slide_names[:100], start=1):
            xml_text = safe_zip_read(zf, name, 10 * 1024 * 1024).decode("utf-8", errors="ignore")
            texts = [unescape(t) for t in re.findall(r"<a:t[^>]*>(.*?)</a:t>", xml_text, re.DOTALL)]
            if texts:
                parts.append(f"## Slayt {number}\n" + "\n".join(texts))
        props = _core_props(zf)
    return ExtractedContent(
        text=clean_text("\n\n".join(parts)),
        metadata={
            "slide_count": len(slide_names),
            "title": props.get("title"),
            "author": props.get("creator"),
        },
        warnings=["Sunumdaki medya/animasyonlar çalıştırılmadı; yalnızca metin çıkarıldı."],
    )


def _extract_epub(data: bytes) -> ExtractedContent:
    zf = open_safe_zip(data)
    with zf:
        names = set(zf.namelist())
        opf_path = ""
        if "META-INF/container.xml" in names:
            container = safe_zip_read(zf, "META-INF/container.xml", 1024 * 1024).decode("utf-8", errors="ignore")
            m = re.search(r'full-path=["\']([^"\']+\.opf)', container)
            if m:
                opf_path = m.group(1)
        if not opf_path:
            opf_path = next((n for n in names if n.lower().endswith(".opf")), "")

        html_files: List[str] = []
        metadata: Dict[str, object] = {}
        if opf_path:
            opf = safe_zip_read(zf, opf_path, 2 * 1024 * 1024).decode("utf-8", errors="ignore")
            try:
                root = _safe_xml(opf)
                ns = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
                for tag in ("title", "creator", "language", "publisher"):
                    node = root.find(f".//dc:{tag}", ns)
                    if node is not None and node.text:
                        metadata[tag] = node.text.strip()[:300]
                manifest = {}
                for item in root.findall(".//opf:manifest/opf:item", ns):
                    manifest[item.get("id")] = item.get("href")
                base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
                for itemref in root.findall(".//opf:spine/opf:itemref", ns):
                    href = manifest.get(itemref.get("idref"))
                    if href:
                        full = (base + href).replace("//", "/")
                        if full in names:
                            html_files.append(full)
            except Exception:
                pass

        if not html_files:
            html_files = [n for n in sorted(names) if n.lower().endswith((".xhtml", ".html", ".htm"))]

        parts: List[str] = []
        total_chars = 0
        for name in html_files[:100]:
            try:
                raw = safe_zip_read(zf, name, 5 * 1024 * 1024).decode("utf-8", errors="ignore")
            except FileAnalysisError:
                continue
            body, _title = html_to_text(raw)
            if not body:
                continue
            parts.append(body)
            total_chars += len(body)
            if total_chars >= MAX_TEXT_CHARS:
                break

    metadata["section_count"] = len(html_files)
    return ExtractedContent(
        text=clean_text("\n\n".join(parts)),
        metadata=metadata,
        warnings=["EPUB içindeki betikler/medya çalıştırılmadı; yalnızca metin çıkarıldı."],
    )


def _extract_pdf(data: bytes) -> ExtractedContent:
    if not HAS_PYPDF:
        raise FileAnalysisError(
            "PDF desteği sunucuda kurulu değil. Yönetici 'pip install pypdf' çalıştırmalıdır.",
            code="missing_dependency", status_code=503,
        )
    try:
        reader = PdfReader(io.BytesIO(data))
        if getattr(reader, "is_encrypted", False):
            raise FileAnalysisError("Şifreli PDF dosyaları analiz edilemez.", code="pdf_encrypted", status_code=422)
        total_pages = len(reader.pages)
        pages: List[str] = []
        for page in reader.pages[:100]:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
        info = reader.metadata or {}
        metadata = {
            "page_count": total_pages,
            "extracted_pages": min(100, total_pages),
            "title": str(info.get("/Title", ""))[:300] or None,
            "author": str(info.get("/Author", ""))[:300] or None,
        }
        text = clean_text("\n\n".join(pages))
        warnings = []
        if not text:
            warnings.append(
                "PDF'ten metin çıkarılamadı. Belge taranmış (görüntü) olabilir; OCR gerekebilir."
            )
        if total_pages > 100:
            warnings.append("PDF'in yalnızca ilk 100 sayfası işlendi.")
        return ExtractedContent(text=text, metadata=metadata, warnings=warnings)
    except FileAnalysisError:
        raise
    except Exception as exc:
        raise FileAnalysisError(
            f"PDF belgesi çözümlenemedi (bozuk veya desteklenmeyen yapı): {str(exc)[:200]}",
            code="pdf_parse_failed", status_code=422,
        ) from exc


def _extract_xlsx(data: bytes) -> ExtractedContent:
    if not HAS_OPENPYXL:
        raise FileAnalysisError(
            "Excel desteği sunucuda kurulu değil. Yönetici 'pip install openpyxl' çalıştırmalıdır.",
            code="missing_dependency", status_code=503,
        )
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    except Exception as exc:
        raise FileAnalysisError(
            f"Excel çalışma kitabı açılamadı: {str(exc)[:200]}", code="xlsx_parse_failed", status_code=422
        ) from exc

    try:
        sheet_names = list(wb.sheetnames)
        parts: List[str] = []
        total_rows = 0
        for sheet_name in sheet_names[:20]:
            ws = wb[sheet_name]
            rows: List[str] = []
            for row_idx, row in enumerate(ws.iter_rows(max_row=500, max_col=40, values_only=True)):
                if row_idx >= 500:
                    break
                cells = ["" if v is None else str(v)[:500] for v in row]
                if any(c.strip() for c in cells):
                    rows.append("\t".join(cells).rstrip())
            total_rows += len(rows)
            if rows:
                parts.append(f"## Sayfa: {sheet_name}\n" + "\n".join(rows))
        metadata = {
            "sheet_count": len(sheet_names),
            "sheet_names": sheet_names[:20],
            "extracted_rows": total_rows,
        }
    finally:
        wb.close()

    warnings = ["Formül sonuçları önbellekte yoksa boş görünebilir; yalnızca hesaplanmış değerler okunur."]
    if len(sheet_names) > 20 or total_rows >= 500:
        warnings.append("Çalışma kitabı ilk 20 sayfa / sayfa başına 500 satır ile sınırlandırıldı.")
    return ExtractedContent(text=clean_text("\n\n".join(parts)), metadata=metadata, warnings=warnings)


# ------------------------------------------------------------
# GÖRSEL / SES / VİDEO
# ------------------------------------------------------------

def _extract_image(data: bytes, detection: Detection) -> ExtractedContent:
    if not HAS_PIL:
        return ExtractedContent(
            text=f"Görsel dosyası: {detection.label}. Sunucuda görsel meta veri kütüphanesi (Pillow) kurulu değil.",
            metadata={"format": detection.format},
            warnings=["Görsel boyutları okunamadı (Pillow eksik)."],
        )
    try:
        img = Image.open(io.BytesIO(data))
        metadata = {
            "format": img.format,
            "width": img.width,
            "height": img.height,
            "mode": img.mode,
            "animated": bool(getattr(img, "is_animated", False)),
            "frames": getattr(img, "n_frames", 1),
        }
        exif = getattr(img, "getexif", lambda: None)()
        if exif:
            exif_meta = {}
            for tag, key in ((271, "make"), (272, "model"), (305, "software")):
                value = exif.get(tag)
                if value:
                    exif_meta[key] = str(value)[:120]
            if exif_meta:
                metadata["exif"] = exif_meta
        summary = (
            f"Görsel: {img.format} • {img.width}x{img.height} piksel • {img.mode} • "
            f"{len(data) / 1024:.1f} KB"
        )
        return ExtractedContent(text=summary, metadata=metadata)
    except Image.DecompressionBombError as exc:
        raise FileAnalysisError(
            "Görsel çok yüksek çözünürlüklü (decompression bomb şüphesi); reddedildi.",
            code="image_bomb", status_code=422,
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise FileAnalysisError(
            "Görsel dosyası açılamadı veya bozuk.", code="image_parse_failed", status_code=422
        ) from exc


def _mp4_duration(data: bytes) -> Optional[float]:
    idx = data.find(b"mvhd", 0, 4 * 1024 * 1024)
    if idx < 0 or idx + 24 > len(data):
        return None
    pos = idx + 4
    try:
        version = data[pos]
        if version == 1:
            timescale = struct.unpack(">I", data[pos + 20:pos + 24])[0]
            duration = struct.unpack(">Q", data[pos + 24:pos + 32])[0]
        else:
            timescale = struct.unpack(">I", data[pos + 12:pos + 16])[0]
            duration = struct.unpack(">I", data[pos + 16:pos + 20])[0]
        return round(duration / timescale, 2) if timescale else None
    except struct.error:
        return None


def _wav_info(data: bytes) -> Dict[str, object]:
    info: Dict[str, object] = {}
    try:
        idx = data.find(b"fmt ", 0, 4096)
        if idx >= 0 and idx + 24 <= len(data):
            audio_format, channels, sample_rate, byte_rate, block_align, bits = struct.unpack(
                "<HHIIHH", data[idx + 8:idx + 24]
            )
            info.update({
                "channels": channels, "sample_rate": sample_rate, "bits_per_sample": bits,
                "audio_format": audio_format,
            })
        data_idx = data.find(b"data", 0, 4096)
        if data_idx >= 0 and data_idx + 8 <= len(data):
            size = struct.unpack("<I", data[data_idx + 4:data_idx + 8])[0]
            byte_rate = info.get("sample_rate", 0) * info.get("channels", 0) * (info.get("bits_per_sample", 0) // 8)
            if byte_rate:
                info["duration_seconds"] = round(size / byte_rate, 2)
    except (struct.error, ZeroDivisionError):
        pass
    return info


def _flac_info(data: bytes) -> Dict[str, object]:
    try:
        idx = data.find(b"STREAMINFO")
        if idx < 0 or idx + 4 + 34 > len(data):
            return {}
        block = data[idx + 4:idx + 4 + 34]
        packed = int.from_bytes(block[10:18], "big")
        sample_rate = (packed >> 44) & 0xFFFFF
        total_samples = packed & 0xFFFFFFFFF
        return {
            "sample_rate": sample_rate,
            "duration_seconds": round(total_samples / sample_rate, 2) if sample_rate else None,
        }
    except Exception:
        return {}


def _extract_media(data: bytes, detection: Detection) -> ExtractedContent:
    fmt = detection.format
    metadata: Dict[str, object] = {"format": fmt, "size_bytes": len(data)}
    if fmt == "wav":
        metadata.update(_wav_info(data))
    elif fmt == "flac":
        metadata.update(_flac_info(data))
    elif fmt in ("mp4", "m4a", "mov", "m4v"):
        duration = _mp4_duration(data)
        if duration:
            metadata["duration_seconds"] = duration
    kind = "Ses" if detection.category == "audio" else "Video"
    duration = metadata.get("duration_seconds")
    duration_text = f" • {duration} sn" if duration else ""
    summary = f"{kind} dosyası: {detection.label}{duration_text} • {len(data) / (1024 * 1024):.2f} MB"
    warnings = ["Medya içeriği çözümlenmedi/oynatılmadı; yalnızca üst bilgi (metadata) okundu."]
    if not duration and detection.category == "video":
        warnings.append("Süre bilgisi bu kapsayıcıdan okunamadı.")
    return ExtractedContent(text=summary, metadata=metadata, warnings=warnings)


# ------------------------------------------------------------
# ARŞİVLER
# ------------------------------------------------------------

def _format_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _archive_listing(entries: List[Tuple[str, int, bool]], total_size: int) -> str:
    lines = [f"Arşiv özeti: {len(entries)} öğe • açılmış toplam {_format_size(total_size)}", ""]
    for name, size, is_dir in entries[:200]:
        safe_name = re.sub(r"[\x00-\x1f\x7f]", "", name)[:200]
        lines.append(f"{'📁' if is_dir else '📄'} {safe_name}" + ("" if is_dir else f"  ({_format_size(size)})"))
    if len(entries) > 200:
        lines.append(f"… ve {len(entries) - 200} öğe daha")
    return "\n".join(lines)


def _extract_zip_archive(data: bytes, detection: Detection) -> ExtractedContent:
    zf = open_safe_zip(data)
    entries: List[Tuple[str, int, bool]] = []
    total = 0
    with zf:
        for info in zf.infolist():
            is_dir = info.is_dir()
            entries.append((info.filename, info.file_size, is_dir))
            total += info.file_size
    warnings = []
    if detection.format in ("apk", "jar"):
        warnings.append("Çalıştırılabilir paket içeriği yalnızca listelendi; hiçbir kod çalıştırılmadı.")
    if detection.format == "zip" and any(n.lower().endswith((".exe", ".dll", ".bat", ".cmd")) for n, _, _ in entries):
        warnings.append("Arşiv çalıştırılabilir dosyalar içeriyor; hiçbiri çalıştırılmadı.")
    return ExtractedContent(
        text=clean_text(_archive_listing(entries, total)),
        metadata={"entry_count": len(entries), "uncompressed_bytes": total},
        warnings=warnings,
    )


def _extract_tar_archive(data: bytes) -> ExtractedContent:
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError as exc:
        raise FileAnalysisError("TAR arşivi açılamadı (bozuk).", code="bad_tar", status_code=422) from exc
    with tf:
        validate_tar(tf)
    # İkinci geçiş: güvenli listeleme
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        entries = [(m.name, m.size, m.isdir()) for m in tf.getmembers()[:2000]]
    total = sum(size for _, size, _ in entries)
    return ExtractedContent(
        text=clean_text(_archive_listing(entries, total)),
        metadata={"entry_count": len(entries), "uncompressed_bytes": total},
        warnings=["TAR içeriği çıkarılmadı; yalnızca güvenli listeleme yapıldı."],
    )


def _extract_compressed(data: bytes, detection: Detection) -> ExtractedContent:
    fmt = detection.format
    metadata: Dict[str, object] = {"format": fmt, "size_bytes": len(data)}
    warnings = ["Sıkıştırılmış içerik açılmadı; yalnızca üst bilgi ve sınırlı örnek okundu."]

    if fmt in ("tgz",) or (fmt == "gz" and detection.extension == ".tgz"):
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                validate_tar(tf)
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                entries = [(m.name, m.size, m.isdir()) for m in tf.getmembers()[:2000]]
            total = sum(size for _, size, _ in entries)
            return ExtractedContent(
                text=clean_text(_archive_listing(entries, total)),
                metadata={"entry_count": len(entries), "uncompressed_bytes": total},
                warnings=["TGZ içeriği çıkarılmadı; yalnızca güvenli listeleme yapıldı."],
            )
        except (tarfile.TarError, FileAnalysisError) as exc:
            if isinstance(exc, FileAnalysisError):
                raise
            warnings.append("TGZ yapısı çözümlenemedi; GZIP üst bilgisi okundu.")

    if fmt == "gz":
        metadata.update(describe_gzip(data))
    elif fmt == "bz2":
        try:
            decomp = bz2.BZ2Decompressor()
            sample = decomp.decompress(data, max_length=4 * 1024 * 1024)
            metadata["uncompressed_sample_bytes"] = len(sample)
            metadata["compressed_bytes"] = len(data)
        except Exception as exc:
            raise FileAnalysisError("BZIP2 dosyası okunamadı.", code="bad_bz2", status_code=422) from exc
    elif fmt == "xz":
        try:
            decomp = lzma.LZMADecompressor()
            sample = decomp.decompress(data, max_length=4 * 1024 * 1024)
            metadata["uncompressed_sample_bytes"] = len(sample)
            metadata["compressed_bytes"] = len(data)
        except Exception as exc:
            raise FileAnalysisError("XZ dosyası okunamadı.", code="bad_xz", status_code=422) from exc

    return ExtractedContent(
        text=f"Sıkıştırılmış dosya: {detection.label} • {_format_size(len(data))}",
        metadata=metadata,
        warnings=warnings,
    )


def _extract_unsupported_archive(detection: Detection) -> ExtractedContent:
    return ExtractedContent(
        text=(
            f"{detection.label} algılandı. Bu arşiv biçimi için güvenli listeleme kütüphanesi "
            "sunucuda bulunmuyor; içerik açılmadı ve çalıştırılmadı."
        ),
        metadata={"format": detection.format},
        warnings=[
            "RAR/7Z içerikleri listelenemedi. Güvenli inceleme için ZIP/TAR olarak yeniden paketleyin."
        ],
    )


# ------------------------------------------------------------
# YÖNLENDİRİCİ
# ------------------------------------------------------------

_LEGACY_MESSAGES = {
    "doc": "Eski Word (.doc) biçimi güvenli şekilde ayrıştırılamıyor. Lütfen belgeyi DOCX veya PDF olarak kaydedip yeniden yükleyin.",
    "xls": "Eski Excel (.xls) biçimi güvenli şekilde ayrıştırılamıyor. Lütfen dosyayı XLSX veya CSV olarak kaydedip yeniden yükleyin.",
    "ppt": "Eski PowerPoint (.ppt) biçimi güvenli şekilde ayrıştırılamıyor. Lütfen sunumu PPTX veya PDF olarak kaydedip yeniden yükleyin.",
}


def extract_content(detection: Detection, data: bytes) -> ExtractedContent:
    fmt = detection.format

    if fmt in _LEGACY_MESSAGES:
        raise FileAnalysisError(_LEGACY_MESSAGES[fmt], code="legacy_office_format", status_code=415)

    if fmt in ("docm", "xlsm", "pptm"):
        raise FileAnalysisError(
            "Makro içeren Office dosyaları güvenlik nedeniyle analiz edilmez. Lütfen makroları kaldırıp yeniden yükleyin.",
            code="macro_document", status_code=422,
        )

    if fmt in ("txt",):
        return extract_plain_text(data, detection)
    if fmt == "md":
        return extract_markdown(data)
    if fmt == "json":
        return extract_json(data)
    if fmt == "yaml":
        return extract_yaml(data)
    if fmt == "csv":
        return extract_csv(data, ",")
    if fmt == "tsv":
        return extract_csv(data, "\t")
    if fmt == "rtf":
        return extract_rtf(data)
    if fmt == "html":
        return extract_html(data)
    if fmt == "xml":
        return extract_xml(data)
    if fmt == "svg":
        return extract_svg(data)
    if fmt == "pdf":
        return _extract_pdf(data)
    if fmt == "docx":
        return _extract_docx(data)
    if fmt == "odt":
        return _extract_odf(data, "odt")
    if fmt == "ods":
        return _extract_odf(data, "ods")
    if fmt == "odp":
        return _extract_odf(data, "odp")
    if fmt == "pptx":
        return _extract_pptx(data)
    if fmt == "epub":
        return _extract_epub(data)
    if fmt == "xlsx":
        return _extract_xlsx(data)
    if fmt == "code":
        return extract_plain_text(data, detection)

    if detection.category == "image":
        return _extract_image(data, detection)
    if detection.category in ("audio", "video"):
        return _extract_media(data, detection)

    if fmt in ("zip", "apk", "jar"):
        return _extract_zip_archive(data, detection)
    if fmt == "tar":
        return _extract_tar_archive(data)
    if fmt in ("gz", "tgz", "bz2", "xz"):
        return _extract_compressed(data, detection)
    if fmt in ("rar", "7z"):
        return _extract_unsupported_archive(detection)

    raise FileAnalysisError(
        f"'{detection.label}' biçimi için içerik çıkarımı desteklenmiyor.",
        code="unsupported_format", status_code=415,
    )
