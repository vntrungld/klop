import QtQuick
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support
import "../code/backend.js" as Backend

PlasmoidItem {
    id: root

    property double savedTotal: 0
    property alias historyModel: historyModel

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
        exec.run(shquote(Backend.CLOP_BIN) + " optimize " + args, function (code, out, err) {
            refreshHistory();
        });
    }

    function optimizeUrls(urls) {
        for (var i = 0; i < urls.length; i++) {
            exec.run(shquote(Backend.CLOP_BIN) + " optimize-url " + shquote(urls[i]), function (code, out, err) {
                refreshHistory();
            });
        }
    }

    function refreshHistory() {
        exec.run(shquote(Backend.CLOP_BIN) + " history --json", function (code, out, err) {
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
        exec.run(shquote(Backend.CLOP_BIN) + " undo " + shquote(backupId), function (code, out, err) {
            refreshHistory();
        });
    }

    // Panel icon == drop target.
    compactRepresentation: Item {
        Kirigami.Icon {
            anchors.fill: parent
            source: "image-x-generic"
            active: dropArea.containsDrag
        }
        DropArea {
            id: dropArea
            anchors.fill: parent
            onEntered: (drag) => {
                if (drag.hasUrls || drag.hasText)
                    drag.accepted = true;
            }
            onDropped: (drop) => {
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
                    var t = drop.text.split(/\s+/)[0];
                    if (t.indexOf("http://") === 0 || t.indexOf("https://") === 0)
                        remotes.push(t);
                }
                if (locals.length)
                    root.optimizePaths(locals);
                if (remotes.length)
                    root.optimizeUrls(remotes);
            }
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
