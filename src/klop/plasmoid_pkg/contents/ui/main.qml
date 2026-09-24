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

    // Jobs this widget started. The executable data source only reports back
    // on completion, so live progress comes from the state files below.
    property int pendingCount: 0

    // Live progress of every running `klop optimize` (including ones started
    // from Dolphin), read from $XDG_RUNTIME_DIR/klop/progress/<pid>.json.
    // progressPercent is -1 when there is nothing to report.
    property int activeRuns: 0
    property int progressPercent: -1
    property string progressName: ""
    readonly property bool busy: pendingCount > 0 || activeRuns > 0

    // Mirrors `clipboard_watch` in the config; the daemon watches the config
    // file and applies changes live.
    property bool clipboardWatch: true

    // Shared history model consumed by the full representation (Task 6).
    ListModel { id: historyModel }

    // Files still being optimized (running + queued) across all runs, shown
    // above the history with a progress bar each.
    property alias pendingModel: pendingModel
    ListModel { id: pendingModel }
    property int doneTotal: 0

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

    property bool polling: false
    function pollProgress() {
        if (polling)
            return;
        polling = true;
        // Skip files whose run is gone (killed before it could clean up).
        exec.run("for f in \"${XDG_RUNTIME_DIR:-/tmp}\"/klop/progress/*.json; do"
                 + " p=${f##*/}; [ -d \"/proc/${p%.json}\" ] && cat \"$f\"; done; true",
                 function (code, out, err) {
            polling = false;
            var runs = [];
            var lines = String(out || "").split("\n");
            for (var i = 0; i < lines.length; i++) {
                if (!lines[i].trim())
                    continue;
                try { runs.push(JSON.parse(lines[i])); } catch (e) {}
            }
            var done = 0;
            var rows = [];
            for (var k = 0; k < runs.length; k++) {
                done += runs[k].done;
                var pending = runs[k].pending || [];
                for (var m = 0; m < pending.length; m++) {
                    rows.push({
                        name: pending[m].name,
                        running: pending[m].state === "running",
                        percent: pending[m].percent
                    });
                }
            }
            // Update rows in place when the shape is unchanged, so the bars
            // don't get rebuilt (and their animations restarted) every poll.
            if (rows.length !== pendingModel.count) {
                pendingModel.clear();
                for (var r = 0; r < rows.length; r++)
                    pendingModel.append(rows[r]);
            } else {
                for (var q = 0; q < rows.length; q++)
                    pendingModel.set(q, rows[q]);
            }
            // A file finished (moves into history) or a run ended.
            var finished = activeRuns > runs.length || done > doneTotal;
            doneTotal = done;
            activeRuns = runs.length;
            if (runs.length === 0) {
                progressPercent = -1;
                progressName = "";
            } else {
                var sum = 0;
                for (var j = 0; j < runs.length; j++)
                    sum += runs[j].percent;
                progressPercent = Math.round(sum / runs.length);
                progressName = runs.length === 1
                    ? runs[0].name + (runs[0].total > 1
                        ? " (" + (runs[0].done + 1) + "/" + runs[0].total + ")" : "")
                    : runs.length + " jobs";
            }
            if (finished)
                refreshHistory();  // a Dolphin run just ended
        });
    }

    Timer {
        interval: root.busy ? 500 : 3000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.pollProgress()
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

    function refreshConfig() {
        exec.run(shquote(Backend.KLOP_BIN) + " config get --json", function (code, out, err) {
            if (code !== 0)
                return;
            try {
                clipboardWatch = JSON.parse(out).clipboard_watch === true;
            } catch (e) {}
        });
    }

    function setClipboardWatch(on) {
        clipboardWatch = on;
        exec.run(shquote(Backend.KLOP_BIN) + " config set clipboard_watch="
                 + (on ? "true" : "false"), function (code, out, err) {
            refreshConfig();
        });
    }

    function undoEntry(backupId) {
        if (!backupId)
            return;
        exec.run(shquote(Backend.KLOP_BIN) + " undo " + shquote(backupId), function (code, out, err) {
            refreshHistory();
        });
    }

    // "image", "video" or "pdf", from the file name; drives row button labels.
    function mediaKind(name) {
        var ext = String(name).toLowerCase().replace(/^.*\./, "");
        if (["mp4", "mov", "mkv", "webm"].indexOf(ext) >= 0)
            return "video";
        if (ext === "pdf")
            return "pdf";
        return "image";
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
                text: dropArea.containsDrag ? "Drop to optimize"
                    : root.progressPercent >= 0 ? "Klop · " + root.progressPercent + "%"
                    : root.busy ? "Klop · …"
                    : "Klop · " + root.humanSize(root.savedTotal)
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
        if (expanded) {
            refreshHistory();
            refreshConfig();
        }
    }

    Component.onCompleted: {
        refreshHistory();
        refreshConfig();
    }
}
