import QtQuick
import QtQuick.Layouts
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support
import "../code/backend.js" as Backend
import "../code/drop.js" as Drop

PlasmoidItem {
    id: root

    property double savedTotal: 0
    property alias historyModel: historyModel

    // Jobs currently running. The executable data source only reports back on
    // completion, so we can't show a real percentage — the full representation
    // shows an indeterminate bar while this is > 0.
    property int pendingCount: 0

    // Shared history model consumed by the full representation (Task 6).
    ListModel { id: historyModel }

    preferredRepresentation: compactRepresentation

    // One executable data source; each run connects a command source, reads the
    // result, then disconnects. `callbacks` maps a command string to its handler.
    P5Support.DataSource {
        id: exec
        engine: "executable"
        connectedSources: []
        property var callbacks: ({})
        onNewData: (source, data) => {
            var cb = callbacks[source];
            disconnectSource(source);
            if (cb) {
                delete callbacks[source];
                cb(data["exit code"], data["stdout"], data["stderr"]);
            }
        }
        function run(cmd, cb) {
            callbacks[cmd] = cb;
            connectSource(cmd);
        }
    }

    function shquote(s) {
        return "'" + String(s).replace(/'/g, "'\\''") + "'";
    }

    function optimizePaths(paths) {
        if (!paths || paths.length === 0)
            return;
        var args = paths.map(shquote).join(" ");
        pendingCount++;
        exec.run(shquote(Backend.KLOP_BIN) + " optimize " + args, function (code, out, err) {
            pendingCount--;
            refreshHistory();
        });
    }

    // Each entry is a list of alternative URLs for one image, tried in order.
    function optimizeUrls(candidateLists) {
        for (var i = 0; i < candidateLists.length; i++) {
            pendingCount++;
            var args = candidateLists[i].map(shquote).join(" ");
            exec.run(shquote(Backend.KLOP_BIN) + " optimize-url " + args, function (code, out, err) {
                pendingCount--;
                refreshHistory();
            });
        }
    }

    // Row actions in the history list. `path` is null for clipboard entries.
    function openImage(path) {
        if (path)
            exec.run("xdg-open " + shquote(path), function () {});
    }

    function openFolder(path) {
        if (!path)
            return;
        // Highlight the file in Dolphin; fall back to opening its directory.
        var dir = String(path).replace(/\/[^/]*$/, "");
        exec.run("dolphin --select " + shquote(path)
                 + " || xdg-open " + shquote(dir), function () {});
    }

    function copyImage(path) {
        if (path)
            exec.run(shquote(Backend.KLOP_BIN) + " copy " + shquote(path), function () {});
    }

    function refreshHistory() {
        exec.run(shquote(Backend.KLOP_BIN) + " history --json", function (code, out, err) {
            if (code !== 0)
                return;
            var rows;
            try {
                rows = JSON.parse(out);
            } catch (e) {
                return;
            }
            historyModel.clear();
            var total = 0;
            for (var i = 0; i < rows.length; i++) {
                var r = rows[i];
                total += Math.max(0, r.original_size - r.new_size);
                historyModel.append({
                    entryId: String(r.id),
                    kind: r.kind,
                    name: r.name,
                    path: r.path ? String(r.path) : "",
                    originalSize: r.original_size,
                    newSize: r.new_size,
                    backupId: r.backup_id ? String(r.backup_id) : "",
                    undone: r.undone === true
                });
            }
            savedTotal = total;
        });
    }

    function undoEntry(backupId) {
        if (!backupId)
            return;
        exec.run(shquote(Backend.KLOP_BIN) + " undo " + shquote(backupId), function (code, out, err) {
            refreshHistory();
        });
    }

    function humanSize(bytes) {
        var units = ["B", "KB", "MB", "GB"];
        var n = bytes, i = 0;
        while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
        return (i === 0 ? n : n.toFixed(1)) + units[i];
    }

    // Shared by the panel item and the popup, which are both drop targets.
    function acceptsDrag(drag) {
        return drag.hasUrls || drag.hasText || drag.hasHtml;
    }

    function handleDrop(drop) {
        var locals = [];
        var remotes = [];
        var urls = drop.hasUrls ? drop.urls : [];
        for (var i = 0; i < urls.length; i++) {
            var raw = urls[i].toString();
            if (raw.indexOf("http://") === 0 || raw.indexOf("https://") === 0) {
                remotes.push(raw);  // keep the URL encoded for fetching
            } else if (raw.indexOf("file://") === 0) {
                var u;
                try { u = decodeURIComponent(raw); } catch (e) { u = raw; }
                locals.push(u.substring("file://".length));
            }
        }
        if (!urls.length && drop.hasText) {
            var t = drop.text.trim().split(/\s+/)[0];
            if (t.indexOf("http://") === 0 || t.indexOf("https://") === 0)
                remotes.push(t);
        }
        if (locals.length)
            root.optimizePaths(locals);
        // A dragged linked image (e.g. on Facebook) puts the link's
        // page URL in the uri-list; the image URL is only in the HTML.
        // Try the <img src> first and keep the dropped URLs as fallback.
        var srcs = drop.hasHtml ? Drop.imageSrcs(drop.html) : [];
        if (srcs.length && remotes.length)
            root.optimizeUrls([srcs.concat(remotes)]);
        else if (remotes.length)
            root.optimizeUrls(remotes.map(function (u) { return [u]; }));
        else if (srcs.length && !locals.length)
            root.optimizeUrls([srcs]);
    }

    // Panel item == drop target: icon plus the saved total, so it is wider
    // than a bare icon. Hovering a drag over it opens the popup, which is a
    // much bigger drop zone.
    compactRepresentation: Item {
        id: compact
        readonly property bool vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical
        Layout.minimumWidth: vertical ? -1 : row.implicitWidth + Kirigami.Units.smallSpacing * 2
        Layout.preferredWidth: Layout.minimumWidth

        RowLayout {
            id: row
            anchors.centerIn: parent
            height: parent.height
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                Layout.preferredWidth: Math.min(parent.height, Kirigami.Units.iconSizes.medium)
                Layout.preferredHeight: Layout.preferredWidth
                source: "image-x-generic"
                active: dropArea.containsDrag
            }
            PlasmaComponents.Label {
                visible: !compact.vertical
                text: dropArea.containsDrag ? "Drop to optimize" : "Klop · " + root.humanSize(root.savedTotal)
            }
        }
        DropArea {
            id: dropArea
            anchors.fill: parent
            onEntered: (drag) => {
                if (root.acceptsDrag(drag)) {
                    drag.accepted = true;
                    hoverOpenTimer.restart();
                }
            }
            onExited: hoverOpenTimer.stop()
            onDropped: (drop) => {
                hoverOpenTimer.stop();
                root.handleDrop(drop);
            }
        }
        Timer {
            id: hoverOpenTimer
            interval: 600
            onTriggered: root.expanded = true
        }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            onClicked: root.expanded = !root.expanded
        }
    }

    fullRepresentation: FullRepresentation { controller: root }

    onExpandedChanged: {
        if (expanded)
            refreshHistory();
    }

    Component.onCompleted: refreshHistory()
}
