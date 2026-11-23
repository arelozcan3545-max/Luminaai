// ============================================================
// LUMINA AI - CITATION UI (CANLI ARAMA KAYNAKLARI)
// ------------------------------------------------------------
// Sunucudan gelen gerçek arama sonuçlarını tıklanabilir kaynak
// listesine çevirir. Yalnızca http(s) adresleri kabul edilir;
// javascript:, data:, dosya yolu ve kimlik bilgisi içeren adresler
// sessizce atlanır. Kaynak uydurulmaz, boş liste HTML üretmez.
// Bu dosya saf yardımcılar içerir; API anahtarı barındırmaz.
// ============================================================

(function (global) {
    "use strict";

    const MAX_CITATIONS = 8;

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function safeHttpUrl(rawUrl) {
        const value = String(rawUrl ?? "").trim().replace(/[\u0000-\u001f\u007f]/g, "");
        if (!value || value.startsWith("//")) return "";
        if (!/^https?:\/\//i.test(value)) return "";
        try {
            const parsed = new URL(value);
            if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
            // Kullanıcı adı/parola içeren adresler kaynak olarak gösterilmez.
            if (parsed.username || parsed.password) return "";
            return parsed.href;
        } catch (e) {
            return "";
        }
    }

    function normalizeCitation(citation) {
        if (!citation || typeof citation !== "object") return null;
        const url = safeHttpUrl(citation.url);
        if (!url) return null;

        let host = String(citation.domain || "").trim();
        if (!host) {
            try { host = new URL(url).hostname; } catch (e) { host = ""; }
        }
        const title = String(citation.title || host || url).trim() || url;
        const published = citation.published_at
            ? `Yayın: ${String(citation.published_at)}`
            : "Yayın tarihi belirtilmemiş";
        const retrieved = citation.retrieved_at ? `Alınma: ${String(citation.retrieved_at)}` : "";

        return {
            url: url,
            host: host.slice(0, 120),
            title: title.slice(0, 200),
            published: published,
            retrieved: retrieved,
            meta: [host, published, retrieved].filter(Boolean).join(" · ")
        };
    }

    function buildCitationSourcesHTML(citations) {
        const rows = [];
        const seen = new Set();
        (Array.isArray(citations) ? citations : []).forEach((citation) => {
            if (rows.length >= MAX_CITATIONS) return;
            const item = normalizeCitation(citation);
            if (!item || seen.has(item.url)) return;
            seen.add(item.url);
            rows.push(
                `<li><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a>` +
                `<span class="citation-meta">${escapeHtml(item.meta)}</span></li>`
            );
        });
        if (!rows.length) return "";
        return `<div class="citations-block"><div class="citations-title">🔗 Kaynaklar</div><ol>${rows.join("")}</ol></div>`;
    }

    const api = {
        escapeHtml: escapeHtml,
        safeHttpUrl: safeHttpUrl,
        normalizeCitation: normalizeCitation,
        buildCitationSourcesHTML: buildCitationSourcesHTML,
        __test: {
            MAX_CITATIONS: MAX_CITATIONS,
            escapeHtml: escapeHtml,
            safeHttpUrl: safeHttpUrl,
            normalizeCitation: normalizeCitation,
            buildCitationSourcesHTML: buildCitationSourcesHTML
        }
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    }
    global.LuminaCitationUI = api;
})(typeof window !== "undefined" ? window : globalThis);
