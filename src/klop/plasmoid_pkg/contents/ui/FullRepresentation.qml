import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami

Item {
    id: full

    // Wired in from main.qml (`fullRepresentation: FullRepresentation { controller: root }`)
    // since this file is a separate QML scope and cannot see main.qml's ids directly.
    property var controller

    Layout.minimumWidth: Kirigami.Units.gridUnit * 18
    Layout.minimumHeight: Kirigami.Units.gridUnit * 20

    function humanSize(bytes) {
        return controller.humanSize(bytes);
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            Kirigami.Heading {
                level: 3
                text: "Saved " + full.humanSize(controller.savedTotal)
                Layout.fillWidth: true
            }
            PlasmaComponents.ToolButton {
                icon.name: "edit-paste"
                checkable: true
                checked: controller.clipboardWatch
                onToggled: controller.setClipboardWatch(checked)
                PlasmaComponents.ToolTip {
                    text: controller.clipboardWatch
                          ? "Clipboard auto-optimize: on"
                          : "Clipboard auto-optimize: off"
                }
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

        // Live progress from the running optimize jobs' state files (a real
        // percentage for videos); indeterminate until the first report lands.
        RowLayout {
            Layout.fillWidth: true
            visible: controller.busy
            spacing: Kirigami.Units.smallSpacing
            PlasmaComponents.Label {
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                elide: Text.ElideMiddle
                Layout.maximumWidth: full.width / 2
                text: controller.progressName ? controller.progressName : "Optimizing…"
            }
            QQC2.ProgressBar {
                Layout.fillWidth: true
                indeterminate: controller.progressPercent < 0
                from: 0
                to: 100
                value: Math.max(0, controller.progressPercent)
            }
            PlasmaComponents.Label {
                font: Kirigami.Theme.smallFont
                visible: controller.progressPercent >= 0
                text: controller.progressPercent + "%"
            }
        }

        PlasmaComponents.ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ListView {
                id: view
                model: controller.historyModel
                clip: true

                // Files still being optimized, one row each, above the history.
                header: ColumnLayout {
                    width: ListView.view.width
                    spacing: 0
                    Repeater {
                        model: controller.pendingModel
                        delegate: PlasmaComponents.ItemDelegate {
                            Layout.fillWidth: true
                            contentItem: ColumnLayout {
                                spacing: Kirigami.Units.smallSpacing
                                RowLayout {
                                    PlasmaComponents.Label {
                                        text: model.name
                                        elide: Text.ElideMiddle
                                        Layout.fillWidth: true
                                    }
                                    PlasmaComponents.Label {
                                        font: Kirigami.Theme.smallFont
                                        opacity: 0.7
                                        text: !model.running ? "Waiting…"
                                            : model.percent >= 0 ? model.percent + "%"
                                            : "Optimizing…"
                                    }
                                }
                                QQC2.ProgressBar {
                                    Layout.fillWidth: true
                                    from: 0
                                    to: 100
                                    value: Math.max(0, model.percent)
                                    indeterminate: model.running && model.percent < 0
                                    opacity: model.running ? 1 : 0.4
                                }
                            }
                        }
                    }
                }
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
                            readonly property string kind: controller.mediaKind(model.name)
                            icon.name: kind === "video" ? "media-playback-start"
                                     : kind === "pdf" ? "application-pdf" : "document-open"
                            visible: model.path !== ""
                            QQC2.ToolTip.text: kind === "video" ? "Open video"
                                             : kind === "pdf" ? "Open PDF" : "Open image"
                            QQC2.ToolTip.visible: hovered
                            onClicked: controller.openImage(model.path)
                        }
                        PlasmaComponents.ToolButton {
                            icon.name: "folder-open"
                            visible: model.path !== ""
                            QQC2.ToolTip.text: "Open folder"
                            QQC2.ToolTip.visible: hovered
                            onClicked: controller.openFolder(model.path)
                        }
                        PlasmaComponents.ToolButton {
                            icon.name: "edit-copy"
                            // `klop copy` puts image data on the clipboard; it
                            // can't do that for videos or PDFs.
                            visible: model.path !== "" && controller.mediaKind(model.name) === "image"
                            QQC2.ToolTip.text: "Copy image"
                            QQC2.ToolTip.visible: hovered
                            onClicked: controller.copyImage(model.path)
                        }
                        PlasmaComponents.ToolButton {
                            icon.name: "edit-undo"
                            visible: model.backupId !== "" && !model.undone
                            QQC2.ToolTip.text: "Undo"
                            QQC2.ToolTip.visible: hovered
                            onClicked: controller.undoEntry(model.backupId)
                        }
                    }
                }

                PlasmaExtras.PlaceholderMessage {
                    anchors.centerIn: parent
                    width: parent.width - Kirigami.Units.gridUnit * 4
                    visible: view.count === 0 && controller.pendingModel.count === 0
                    text: "No optimizations yet"
                }
            }
        }
    }

    // The whole popup is a drop zone; it opens when a drag hovers the panel item.
    DropArea {
        id: popupDrop
        anchors.fill: parent
        onEntered: (drag) => {
            if (controller.acceptsDrag(drag))
                drag.accepted = true;
        }
        onDropped: (drop) => controller.handleDrop(drop)
    }

    Rectangle {
        anchors.fill: parent
        visible: popupDrop.containsDrag
        radius: Kirigami.Units.cornerRadius
        color: Qt.alpha(Kirigami.Theme.highlightColor, 0.15)
        border.color: Kirigami.Theme.highlightColor
        border.width: 2

        ColumnLayout {
            anchors.centerIn: parent
            Kirigami.Icon {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: Kirigami.Units.iconSizes.huge
                Layout.preferredHeight: Kirigami.Units.iconSizes.huge
                source: "document-import"
            }
            Kirigami.Heading {
                Layout.alignment: Qt.AlignHCenter
                level: 3
                text: "Drop to optimize"
            }
        }
    }
}
