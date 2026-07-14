import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: full

    // Wired in from main.qml (`fullRepresentation: FullRepresentation { controller: root }`)
    // since this file is a separate QML scope and cannot see main.qml's ids directly.
    property var controller

    Layout.minimumWidth: Kirigami.Units.gridUnit * 18
    Layout.minimumHeight: Kirigami.Units.gridUnit * 20
    spacing: Kirigami.Units.smallSpacing

    function humanSize(bytes) {
        var units = ["B", "KB", "MB", "GB"];
        var n = bytes, i = 0;
        while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
        return (i === 0 ? n : n.toFixed(1)) + units[i];
    }

    RowLayout {
        Layout.fillWidth: true
        Kirigami.Heading {
            level: 3
            text: "Saved " + full.humanSize(controller.savedTotal)
            Layout.fillWidth: true
        }
        PlasmaComponents.ToolButton {
            icon.name: "view-refresh"
            onClicked: controller.refreshHistory()
        }
        PlasmaComponents.ToolButton {
            icon.name: "configure"
            onClicked: Plasmoid.internalAction("configure").trigger()
        }
    }

    PlasmaComponents.ScrollView {
        Layout.fillWidth: true
        Layout.fillHeight: true

        ListView {
            id: view
            model: controller.historyModel
            clip: true
            delegate: PlasmaComponents.ItemDelegate {
                width: ListView.view.width
                contentItem: RowLayout {
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        PlasmaComponents.Label {
                            text: model.name
                            elide: Text.ElideMiddle
                            Layout.fillWidth: true
                        }
                        PlasmaComponents.Label {
                            font: Kirigami.Theme.smallFont
                            opacity: 0.7
                            text: full.humanSize(model.originalSize) + " → "
                                  + full.humanSize(model.newSize)
                                  + (model.originalSize > 0
                                     ? "  (-" + Math.round(
                                         (1 - model.newSize / model.originalSize) * 100) + "%)"
                                     : "")
                                  + (model.undone ? "  [undone]" : "")
                        }
                    }
                    PlasmaComponents.ToolButton {
                        icon.name: "edit-undo"
                        visible: model.backupId !== "" && !model.undone
                        onClicked: controller.undoEntry(model.backupId)
                    }
                }
            }

            PlasmaExtras.PlaceholderMessage {
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.gridUnit * 4
                visible: view.count === 0
                text: "No optimizations yet"
            }
        }
    }
}
