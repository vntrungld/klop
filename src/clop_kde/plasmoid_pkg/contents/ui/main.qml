import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support
import "../code/backend.js" as Backend

PlasmoidItem {
    id: root

    property int savedTotal: 0
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
                if (drag.hasUrls)
                    drag.accepted = true;
            }
            onDropped: (drop) => {
                var paths = [];
                for (var i = 0; i < drop.urls.length; i++) {
                    var u = decodeURIComponent(drop.urls[i].toString());
                    if (u.indexOf("file://") === 0)
                        paths.push(u.substring("file://".length));
                }
                if (paths.length)
                    root.optimizePaths(paths);
            }
        }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            onClicked: root.expanded = !root.expanded
        }
    }

    // Placeholder until Task 6 replaces it with the real popup.
    fullRepresentation: ColumnLayout {
        Kirigami.Heading { text: "Klop" }
    }

    Component.onCompleted: refreshHistory()
}
