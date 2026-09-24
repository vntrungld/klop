import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support
import "../code/backend.js" as Backend

ColumnLayout {
    id: page

    property bool loaded: false

    spacing: Kirigami.Units.largeSpacing

    P5Support.DataSource {
        id: exec
        engine: "executable"
        connectedSources: []
        property var callbacks: ({})
        onNewData: (source, data) => {
            var cb = callbacks[source];
            disconnectSource(source);
            if (cb) { delete callbacks[source]; cb(data["exit code"], data["stdout"], data["stderr"]); }
        }
        function run(cmd, cb) { callbacks[cmd] = cb; connectSource(cmd); }
    }

    // Big left-aligned page title, KDE settings style. gridUnit margins around
    // the content match the padding of a standard KDE settings page.
    Kirigami.Heading {
        Layout.fillWidth: true
        Layout.topMargin: Kirigami.Units.largeSpacing * 1.5 - 1
        Layout.leftMargin: Kirigami.Units.gridUnit
        Layout.rightMargin: Kirigami.Units.gridUnit
        level: 1
        // Bump past the level-1 size for a large KDE-style page title.
        font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.35
        text: "Image optimization"
    }

    Kirigami.FormLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit
        Layout.rightMargin: Kirigami.Units.gridUnit

        QQC2.CheckBox {
            id: pngLossy
            Kirigami.FormData.label: "PNG lossy:"
            text: "Quantize PNGs (pngquant)"
        }
        RowLayout {
            Kirigami.FormData.label: "pngquant quality:"
            QQC2.SpinBox { id: pngMin; from: 0; to: 100 }
            QQC2.Label { text: "→" }
            QQC2.SpinBox { id: pngMax; from: 0; to: 100 }
        }
        QQC2.SpinBox {
            id: jpegMax
            Kirigami.FormData.label: "JPEG max quality:"
            from: 1; to: 100
        }
        QQC2.SpinBox {
            id: webpQuality
            Kirigami.FormData.label: "WebP quality:"
            from: 1; to: 100
        }
        QQC2.SpinBox {
            id: gifLossy
            Kirigami.FormData.label: "GIF lossy (0 = off):"
            from: 0; to: 200
        }
        QQC2.ComboBox {
            id: pdfSetting
            Kirigami.FormData.label: "PDF quality:"
            model: ["screen", "ebook", "printer", "prepress"]
        }
        QQC2.SpinBox {
            id: videoCrf
            Kirigami.FormData.label: "Video CRF:"
            from: 0; to: 51
        }
        QQC2.TextField {
            id: videoCodec
            Kirigami.FormData.label: "Video codec:"
        }
        QQC2.TextField {
            id: videoPreset
            Kirigami.FormData.label: "Video preset:"
        }
        QQC2.SpinBox {
            id: minSaved
            Kirigami.FormData.label: "Min bytes saved:"
            from: 0; to: 1000000
        }
        QQC2.SpinBox {
            id: concurrency
            Kirigami.FormData.label: "Concurrency:"
            from: 1; to: 16
        }
        QQC2.CheckBox {
            id: clipboardWatch
            Kirigami.FormData.label: "Clipboard:"
            text: "Auto-optimize copied images"
        }

        QQC2.Label {
            id: errorLabel
            visible: text !== ""
            color: Kirigami.Theme.negativeTextColor
        }
    }

    // Soak up leftover space so the form stays pinned to the top.
    Item { Layout.fillHeight: true }

    function shquote(s) {
        return "'" + String(s).replace(/'/g, "'\\''") + "'";
    }

    // Plasma calls this when the user hits Apply/OK.
    function saveConfig() {
        if (!page.loaded)
            return;
        var assigns = [
            "png_lossy=" + (pngLossy.checked ? "true" : "false"),
            "pngquant_quality=" + pngMin.value + "," + pngMax.value,
            "jpeg_max_quality=" + jpegMax.value,
            "webp_quality=" + webpQuality.value,
            "gif_lossy=" + gifLossy.value,
            "pdf_setting=" + shquote(pdfSetting.currentValue),
            "video_crf=" + videoCrf.value,
            "video_codec=" + shquote(videoCodec.text),
            "video_preset=" + shquote(videoPreset.text),
            "min_bytes_saved=" + minSaved.value,
            "concurrency=" + concurrency.value,
            "clipboard_watch=" + (clipboardWatch.checked ? "true" : "false")
        ].join(" ");
        exec.run(shquote(Backend.KLOP_BIN) + " config set " + assigns, function (code, out, err) {
            errorLabel.text = (code !== 0) ? (err || "config set failed").trim() : "";
        });
    }

    Component.onCompleted: {
        exec.run(shquote(Backend.KLOP_BIN) + " config get --json", function (code, out, err) {
            if (code !== 0) return;
            var c;
            try { c = JSON.parse(out); } catch (e) { return; }
            pngLossy.checked = c.png_lossy === true;
            pngMin.value = c.pngquant_quality[0];
            pngMax.value = c.pngquant_quality[1];
            jpegMax.value = c.jpeg_max_quality;
            webpQuality.value = c.webp_quality;
            gifLossy.value = c.gif_lossy;
            pdfSetting.currentIndex = pdfSetting.model.indexOf(c.pdf_setting);
            videoCrf.value = c.video_crf;
            videoCodec.text = c.video_codec;
            videoPreset.text = c.video_preset;
            minSaved.value = c.min_bytes_saved;
            concurrency.value = c.concurrency;
            clipboardWatch.checked = c.clipboard_watch === true;
            page.loaded = true;
        });
    }
}
