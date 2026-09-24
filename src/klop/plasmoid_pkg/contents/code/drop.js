.pragma library
// Helpers for the panel icon's drop target.

function _unescape(s) {
    return s.replace(/&quot;/g, '"').replace(/&#39;/g, "'")
            .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}

// Remote <img src> URLs in a drag's text/html. Browsers put a linked image's
// link target (e.g. a Facebook photo page) in the uri-list, so the image URL
// itself is only available here.
function imageSrcs(html) {
    var out = [];
    var re = /<img\b[^>]*?\ssrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/gi;
    var m;
    while ((m = re.exec(html || "")) !== null) {
        var src = _unescape((m[1] || m[2] || m[3] || "").trim());
        if (/^https?:\/\//i.test(src) && out.indexOf(src) < 0)
            out.push(src);
    }
    return out;
}
