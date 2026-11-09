import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs
import "../components"

Page {
    id: page
    title: "Settings"
    readonly property var kindIcon: ({ headphones: "headphones", speakers: "speakers", hdmi: "hdmi",
                                       bluetooth: "bluetooth", usb: "usb", other: "speakers" })

    Card {
        width: parent.width
        implicitHeight: outCol.implicitHeight + 56
        height: implicitHeight
        ColumnLayout {
            id: outCol
            anchors.fill: parent; anchors.margins: 28
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                Column { Layout.fillWidth: true
                    Label { text: "Output device"; role: "titleL"; emphasized: true }
                    Label { text: "Where Resona sends processed sound"; role: "body"; color: Theme.inkVariant } }
                Label { text: "Follow system output"; role: "labelL"; color: Theme.inkVariant }
                M3Switch { Accessible.name: "Follow system output"; checked: audio.follow; onToggled: (v) => audio.setFollow(v) }
            }
            Repeater {
                model: audio.sinks
                delegate: Rectangle {
                    id: row
                    required property var modelData
                    readonly property bool sel: audio.output === modelData.name
                    Layout.fillWidth: true
                    height: 64
                    radius: sel ? 32 : 16
                    color: sel ? Theme.secondaryContainer : (ma.containsMouse ? Theme.surfaceContainerHigh : "transparent")
                    Behavior on radius { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack } }
                    Behavior on color { ColorAnimation { duration: Theme.fast } }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 20; anchors.rightMargin: 20
                        spacing: 16
                        Icon { name: page.kindIcon[row.modelData.kind] || "speakers"; size: 24
                               color: row.sel ? Theme.inkSecondaryContainer : Theme.inkVariant }
                        Label { text: row.modelData.description; role: "bodyL"; Layout.fillWidth: true; elide: Text.ElideRight
                                color: row.sel ? Theme.inkSecondaryContainer : Theme.ink; font.weight: row.sel ? Font.DemiBold : Font.Normal }
                        Icon { name: "check"; size: 22; color: Theme.primary; visible: row.sel }
                    }
                    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: audio.setOutput(row.modelData.name) }
                }
            }
        }
    }

    // ---------------------------------------------------- presets
    FileDialog { id: importDlg; title: "Import Resona preset"; nameFilters: ["Resona presets (*.json)"]
                 onAccepted: audio.importPreset(selectedFile) }
    FileDialog { id: exportDlg; property string preset; title: "Export preset"; fileMode: FileDialog.SaveFile
                 nameFilters: ["Resona presets (*.json)"]; onAccepted: audio.exportPreset(preset, selectedFile) }
    Card {
        width: parent.width
        height: presetCol.implicitHeight + 56
        ColumnLayout {
            id: presetCol
            anchors.fill: parent; anchors.margins: 28
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Column { Layout.fillWidth: true
                    Label { text: "My presets"; role: "titleL"; emphasized: true }
                    Label { text: "Snapshot everything (profile, EQ, spatial, correction) and share it as JSON"; role: "body"; color: Theme.inkVariant } }
                Btn { text: "Import…"; icon: "upload"; variant: "outlined"; onClicked: importDlg.open() }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                SearchField { id: presetName; Layout.fillWidth: true; icon: "save"; placeholder: "Name this sound, e.g. “Late-night anime”"
                              onAccepted: (t) => { audio.savePreset(t); presetName.text = "" } }
                Btn { text: "Save"; icon: "save"; size: 56; enabled: presetName.text.trim() !== ""
                      opacity: enabled ? 1 : 0.4; onClicked: { audio.savePreset(presetName.text); presetName.text = "" } }
            }
            Repeater {
                model: audio.userPresets
                delegate: Rectangle {
                    id: pr
                    required property string modelData
                    Layout.fillWidth: true; height: 56; radius: pma.containsMouse ? 28 : 16
                    color: pma.containsMouse ? Theme.surfaceContainerHigh : "transparent"
                    Behavior on radius { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack } }
                    MouseArea { id: pma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: audio.loadPreset(pr.modelData) }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 20; anchors.rightMargin: 8
                        Icon { name: "tune"; size: 22; color: Theme.primary }
                        Label { text: pr.modelData; role: "bodyL"; Layout.fillWidth: true; leftPadding: 8 }
                        Btn { text: "Export"; variant: "text"; size: 32; onClicked: { exportDlg.preset = pr.modelData; exportDlg.open() } }
                        Btn { Accessible.name: "Delete preset " + pr.modelData; icon: "delete"; variant: "text"; size: 32; onClicked: audio.deletePreset(pr.modelData) }
                    }
                }
            }
        }
    }

    // ---------------------------------------------------- smart switching
    Card {
        width: parent.width
        height: smartCol.implicitHeight + 56
        ColumnLayout {
            id: smartCol
            anchors.fill: parent; anchors.margins: 28
            spacing: 14
            RowLayout {
                Layout.fillWidth: true
                Column { Layout.fillWidth: true
                    Label { text: "Route every app through Resona"; role: "titleM"; emphasized: true }
                    Label { text: "Catches games that open your speakers directly (FMOD/Wwise titles like War Thunder), so effects and volume keys apply"
                            role: "body"; color: Theme.inkVariant; width: parent.width; wrapMode: Text.WordWrap } }
                M3Switch { Accessible.name: "Capture apps that bypass Resona"; checked: audio.captureAll; onToggled: (v) => audio.setCaptureAll(v) }
            }
            RowLayout {
                Layout.fillWidth: true
                Column { Layout.fillWidth: true
                    Label { text: "Remember sound per device"; role: "titleM"; emphasized: true }
                    Label { text: "Headphones, speakers, HDMI and Bluetooth each keep their own profile and EQ"; role: "body"; color: Theme.inkVariant } }
                M3Switch { Accessible.name: "Remember sound per device"; checked: audio.perDevice; onToggled: (v) => audio.setPerDevice(v) }
            }
            RowLayout {
                Layout.fillWidth: true
                Column { Layout.fillWidth: true
                    Label { text: "Automatic profile per app"; role: "titleM"; emphasized: true }
                    Label { text: audio.autoApp ? "Active now for " + audio.autoApp : "Movie for mpv & VLC, Music for Spotify, Gaming for Steam, Voice for Discord…"
                            role: "body"; color: Theme.inkVariant } }
                M3Switch { Accessible.name: "Automatic app profiles"; checked: audio.appAuto; onToggled: (v) => audio.setAppAuto(v) }
            }
            Label { visible: audio.apps.length > 0; text: "Playing now"; role: "labelL"; color: Theme.inkVariant; topPadding: 4 }
            Repeater {
                model: audio.apps
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    Icon { name: "apps"; size: 22; color: Theme.inkVariant }
                    Label { text: modelData.name; role: "bodyL"; Layout.fillWidth: true; leftPadding: 8 }
                    SelectButton {
                        current: modelData.profile; placeholder: "No profile"
                        options: [""].concat(audio.profiles.map(p => p.name))
                        onPicked: (v) => audio.setAppRule(modelData.binary, v)
                    }
                }
            }
        }
    }

    Card {
        width: parent.width
        height: 210
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 28
            spacing: 18
            RowLayout {
                Layout.fillWidth: true
                Column { Layout.fillWidth: true
                    Label { text: "Color"; role: "titleL"; emphasized: true }
                    Label { text: "The whole interface re-tones from one seed"; role: "body"; color: Theme.inkVariant } }
                Label { text: "Dark"; role: "labelL"; color: Theme.inkVariant }
                M3Switch { Accessible.name: "Dark theme"; checked: audio.dark; onToggled: (v) => audio.setDark(v) }
            }
            Row {
                spacing: 14
                Repeater {
                    model: audio.accents
                    delegate: MorphShape {
                        required property string modelData
                        readonly property bool sel: audio.accent === modelData
                        width: 64; height: 64
                        shape: sel ? "cookie9" : "circle"
                        spinning: sel
                        color: modelData
                        color2: Qt.lighter(modelData, 1.25)
                        scale: sma.pressed ? 0.9 : (sma.containsMouse ? 1.06 : 1)
                        Behavior on scale { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack } }
                        Icon { anchors.centerIn: parent; name: "check"; size: 26; color: "#1b1b1f"; visible: parent.sel }
                        MouseArea { id: sma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: audio.setAccent(parent.modelData) }
                    }
                }
            }
        }
    }

    // ---------------------------------------------------- updates
    Card {
        id: updCard
        readonly property var u: audio.updateInfo
        readonly property bool busy: u.state === "checking" || u.state === "installing" || u.state === "restarting"
        width: parent.width
        height: updCol.implicitHeight + 56
        color: u.state === "available" ? Theme.mix(Theme.primaryContainer, Theme.surfaceContainer, 0.55) : Theme.surfaceContainer
        Behavior on color { ColorAnimation { duration: Theme.medium } }
        ColumnLayout {
            id: updCol
            anchors.fill: parent; anchors.margins: 28
            spacing: 16
            RowLayout {
                Layout.fillWidth: true
                spacing: 18
                MorphShape {
                    width: 56; height: 56
                    Layout.preferredWidth: 56; Layout.preferredHeight: 56
                    shape: updCard.busy ? "burst12" : updCard.u.state === "available" ? "flower8" : "cookie9"
                    color: updCard.u.state === "error" ? Theme.error : Theme.primary
                    color2: Theme.tertiary
                    spinning: updCard.busy
                    spinDuration: 2400
                    Icon { anchors.centerIn: parent; size: 26; color: Theme.inkPrimary
                           name: updCard.u.state === "available" ? "download" : updCard.u.state === "current" ? "check" : "rocket" }
                }
                Column {
                    Layout.fillWidth: true
                    Label { text: "Updates"; role: "titleL"; emphasized: true }
                    Label {
                        width: parent.width; wrapMode: Text.WordWrap
                        role: "body"; color: Theme.inkVariant
                        text: (updCard.u.message || ("Resona " + audio.version + ", straight from GitHub releases"))
                              + (updCard.u.last && !updCard.busy ? "  ·  last checked " + new Date(updCard.u.last * 1000).toLocaleDateString() : "")
                    }
                }
                Btn {
                    visible: updCard.u.state === "available" && updCard.u.kind === "user"
                    text: "Update now"; icon: "download"; size: 56
                    onClicked: audio.installUpdate()
                }
                Btn {
                    visible: updCard.u.state !== "available" || updCard.u.kind !== "user"
                    text: updCard.busy ? "Working…" : "Check now"; icon: "reset"; variant: "tonal"; size: 56
                    enabled: !updCard.busy; opacity: enabled ? 1 : 0.6
                    onClicked: audio.checkUpdates()
                }
            }
            Rectangle {
                visible: updCard.u.state === "available" && updCard.u.notes !== ""
                Layout.fillWidth: true
                implicitHeight: notes.implicitHeight + 32
                radius: 20
                color: Theme.surfaceContainerHigh
                Label {
                    id: notes
                    anchors.fill: parent; anchors.margins: 16
                    wrapMode: Text.WordWrap; textFormat: Text.MarkdownText
                    role: "body"; color: Theme.ink
                    text: (updCard.u.notes || "").split("\n").slice(0, 14).join("\n")
                    maximumLineCount: 14; elide: Text.ElideRight
                }
            }
            Label {
                visible: updCard.u.kind !== "user"
                Layout.fillWidth: true; wrapMode: Text.WordWrap
                role: "body"; color: Theme.inkVariant
                text: updCard.u.kind === "source" ? "Running from a git checkout, so Resona only checks. Update with git pull."
                                                  : "Installed by your package manager, so Resona only checks. Update it there."
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 16
                Label { text: "Check automatically"; role: "labelL"; color: Theme.inkVariant }
                ButtonGroup {
                    Layout.fillWidth: true
                    Layout.maximumWidth: 460
                    itemHeight: 40
                    current: updCard.u.freq
                    model: [{ key: "manual", label: "Only when I ask" }, { key: "weekly", label: "Weekly" },
                            { key: "monthly", label: "Monthly" }]
                    onPicked: (k) => audio.setUpdateFreq(k)
                }
                Item { Layout.fillWidth: true }
                Label { text: "Install by itself"; role: "labelL"; color: Theme.inkVariant
                        opacity: updCard.u.freq === "manual" ? 0.4 : 1 }
                M3Switch { Accessible.name: "Install updates automatically"; checked: updCard.u.auto; enabled: updCard.u.freq !== "manual" && updCard.u.kind === "user"
                           opacity: enabled ? 1 : 0.4; onToggled: (v) => audio.setUpdateAuto(v) }
            }
        }
    }

    GridLayout {
        width: parent.width
        columns: 2; columnSpacing: 16
        Card {
            Layout.fillWidth: true
            Layout.preferredHeight: 120
            RowLayout {
                anchors.fill: parent; anchors.margins: 28
                Column { Layout.fillWidth: true
                    Label { text: "Start with my session"; role: "titleM"; emphasized: true }
                    Label { text: "Launch quietly to the tray at login"; role: "body"; color: Theme.inkVariant } }
                M3Switch { Accessible.name: "Start Resona at login"; checked: audio.autostart; onToggled: (v) => audio.setAutostart(v) }
            }
        }
        Card {
            Layout.fillWidth: true
            Layout.preferredHeight: 120
            RowLayout {
                anchors.fill: parent; anchors.margins: 28
                spacing: 16
                MorphShape { width: 56; height: 56; shape: "cookie12"; color: Theme.primary; color2: Theme.tertiary; spinning: true
                             Icon { anchors.centerIn: parent; name: "waves"; size: 26; color: Theme.inkPrimary } }
                Column { Layout.fillWidth: true
                    Label { text: "Resona " + audio.version + " · open source (GPL-3.0)"; role: "titleM"; emphasized: true }
                    Label { text: "Native DSP engine · " + (audio.sampleRate / 1000) + " kHz · " + audio.outputLayout.name + " · 1.5 ms lookahead"
                            role: "body"; color: Theme.inkVariant } }
            }
        }
    }
}
