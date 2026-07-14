import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support
import "../code/backend.js" as Backend

Kirigami.FormLayout {
    id: page

    property bool loaded: false

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

    // Plasma calls this when the user hits Apply/OK.
    function saveConfig() {
        var assigns = [
            "png_lossy=" + (pngLossy.checked ? "true" : "false"),
            "pngquant_quality=" + pngMin.value + "," + pngMax.value,
            "jpeg_max_quality=" + jpegMax.value,
            "min_bytes_saved=" + minSaved.value,
            "concurrency=" + concurrency.value,
            "clipboard_watch=" + (clipboardWatch.checked ? "true" : "false")
        ].join(" ");
        exec.run(Backend.CLOP_BIN + " config set " + assigns, function (code, out, err) {
            errorLabel.text = (code !== 0) ? (err || "config set failed").trim() : "";
        });
    }

    Component.onCompleted: {
        exec.run(Backend.CLOP_BIN + " config get --json", function (code, out, err) {
            if (code !== 0) return;
            var c;
            try { c = JSON.parse(out); } catch (e) { return; }
            pngLossy.checked = c.png_lossy === true;
            pngMin.value = c.pngquant_quality[0];
            pngMax.value = c.pngquant_quality[1];
            jpegMax.value = c.jpeg_max_quality;
            minSaved.value = c.min_bytes_saved;
            concurrency.value = c.concurrency;
            clipboardWatch.checked = c.clipboard_watch === true;
            page.loaded = true;
        });
    }
}
