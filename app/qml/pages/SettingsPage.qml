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
                M3Switch { checked: audio.follow; onToggled: (v) => audio.setFollow(v) }
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
                        Btn { icon: "delete"; variant: "text"; size: 32; onClicked: audio.deletePreset(pr.modelData) }
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
                M3Switch { checked: audio.captureAll; onToggled: (v) => audio.setCaptureAll(v) }
            }
            RowLayout {
                Layout.fillWidth: true
                Column { Layout.fillWidth: true
                    Label { text: "Remember sound per device"; role: "titleM"; emphasized: true }
                    Label { text: "Headphones, speakers, HDMI and Bluetooth each keep their own profile and EQ"; role: "body"; color: Theme.inkVariant } }
                M3Switch { checked: audio.perDevice; onToggled: (v) => audio.setPerDevice(v) }
            }
            RowLayout {
                Layout.fillWidth: true
                Column { Layout.fillWidth: true
                    Label { text: "Automatic profile per app"; role: "titleM"; emphasized: true }
                    Label { text: audio.autoApp ? "Active now for " + audio.autoApp : "Movie for mpv & VLC, Music for Spotify, Gaming for Steam, Voice for Discord…"
                            role: "body"; color: Theme.inkVariant } }
                M3Switch { checked: audio.appAuto; onToggled: (v) => audio.setAppAuto(v) }
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
                M3Switch { checked: audio.dark; onToggled: (v) => audio.setDark(v) }
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
                M3Switch { checked: audio.autostart; onToggled: (v) => audio.setAutostart(v) }
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
                    Label { text: "Resona 2.0 · open source (GPL-3.0)"; role: "titleM"; emphasized: true }
                    Label { text: "Native DSP engine · " + (audio.sampleRate / 1000) + " kHz · " + audio.outputLayout.name + " · 1.5 ms latency"
                            role: "body"; color: Theme.inkVariant } }
            }
        }
    }
}
