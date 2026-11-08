import QtQuick
import QtQuick.Layouts
import "../components"

Page {
    id: page
    title: "Resona"
    subtitle: ""
    readonly property var profileIcons: ({ "Dynamic": "sparkle", "Music": "music", "Movie": "movie", "Gaming": "game",
                                           "Voice": "mic", "Night": "moon", "Pure": "waves" })
    readonly property string outputDesc: {
        for (const s of audio.sinks) if (s.name === audio.output) return s.description
        return "No output"
    }

    headerRight: [
        Rectangle {
            height: 40; radius: 20
            width: statusRow.implicitWidth + 32
            color: Theme.surfaceContainerHigh
            Row {
                id: statusRow
                anchors.centerIn: parent
                spacing: 10
                Rectangle {
                    width: 10; height: 10; radius: 5
                    anchors.verticalCenter: parent.verticalCenter
                    color: audio.processing ? "#4ADE80" : audio.running ? Theme.secondary : Theme.error
                    SequentialAnimation on opacity { running: audio.processing; loops: Animation.Infinite
                        NumberAnimation { to: 0.35; duration: 700 } NumberAnimation { to: 1; duration: 700 } }
                }
                Label { text: audio.status + (audio.running ? "  ·  " + (audio.sampleRate / 1000) + " kHz  ·  " + page.outputDesc : "")
                        role: "labelL"; color: Theme.inkVariant; anchors.verticalCenter: parent.verticalCenter }
            }
        },
        Btn {
            text: "Hold to compare"
            icon: "compare"
            variant: "tonal"
            onPressedChanged2: (d) => audio.compare(d)
        }
    ]

    // ---------------------------------------------------------------- hero
    Rectangle {
        id: hero
        width: parent.width
        height: 320
        radius: 44
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.mix(Theme.primaryContainer, Theme.surfaceContainer, audio.params.enable ? 0.15 : 0.85) }
            GradientStop { position: 0.55; color: Theme.surfaceContainer }
            GradientStop { position: 1; color: Theme.mix(Theme.tertiaryContainer, Theme.surfaceContainer, 0.55) }
        }
        clip: true

        Item {
            id: powerArea
            width: 300; height: parent.height
            MorphShape {
                id: power
                anchors.centerIn: parent
                anchors.verticalCenterOffset: -16
                width: 196; height: 196
                shape: audio.params.enable ? "cookie12" : "circle"
                color: audio.params.enable ? Theme.primary : Theme.surfaceContainerHighest
                color2: audio.params.enable ? Theme.tertiary : Theme.surfaceContainerHighest
                spinning: audio.params.enable && audio.processing
                spinDuration: 11000
                breathe: audio.params.enable ? audio.meters.out : 0
                scale: pma.pressed ? 0.92 : 1
                Behavior on scale { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack } }
                Icon { anchors.centerIn: parent; name: "power"; size: 64
                       color: audio.params.enable ? Theme.inkPrimary : Theme.inkVariant }
                MouseArea { id: pma; anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                            onClicked: audio.setEnabled(!audio.params.enable) }
            }
            Label {
                anchors.horizontalCenter: power.horizontalCenter
                anchors.top: power.bottom; anchors.topMargin: 14
                text: audio.params.enable ? "Effects on" : "Bypassed"
                role: "titleM"; emphasized: true
                color: audio.params.enable ? Theme.ink : Theme.inkVariant
            }
        }
        ColumnLayout {
            anchors.left: powerArea.right
            anchors.right: parent.right
            anchors.top: parent.top; anchors.bottom: parent.bottom
            anchors.margins: 32; anchors.leftMargin: 8
            spacing: 2
            Label { text: "NOW SHAPING"; role: "label"; color: Theme.primary; font.letterSpacing: 2.2; emphasized: true }
            RowLayout {
                spacing: 14
                Label { text: audio.profile; role: "displayM"; emphasized: true
                        font.variableAxes: { "wdth": 125, "wght": 850 } }
                Rectangle {
                    visible: audio.modified
                    height: 28; radius: 14; width: mod.implicitWidth + 20
                    color: Theme.tertiaryContainer
                    Label { id: mod; anchors.centerIn: parent; text: "tweaked"; role: "label"; color: Theme.inkTertiaryContainer }
                }
            }
            Label { text: (audio.profiles.find(p => p.name === audio.profile) || {}).desc || ""
                    role: "bodyL"; color: Theme.inkVariant }
            Item { Layout.fillWidth: true; Layout.fillHeight: true
                Spectrum { anchors.fill: parent; anchors.topMargin: 12 }
                Row {
                    anchors.right: parent.right; anchors.top: parent.top; spacing: 16
                    Row { spacing: 6
                        Rectangle { width: 16; height: 3; radius: 2; color: Theme.inkVariant; opacity: 0.6; anchors.verticalCenter: parent.verticalCenter }
                        Label { text: "original"; role: "label"; color: Theme.inkVariant } }
                    Row { spacing: 6
                        Rectangle { width: 16; height: 4; radius: 2; color: Theme.primary; anchors.verticalCenter: parent.verticalCenter }
                        Label { text: "Resona"; role: "label"; color: Theme.inkVariant } }
                }
                Label {
                    anchors.centerIn: parent
                    visible: !audio.processing
                    text: audio.running ? "Play something and the analyzer wakes up with your audio" : audio.status
                    role: "bodyL"; color: Theme.inkVariant
                }
            }
        }
    }

    // ---------------------------------------------------------------- profiles
    Label { text: "Sound profile"; role: "titleL"; emphasized: true; topPadding: 8 }
    GridLayout {
        id: grid
        width: parent.width
        columns: Math.max(3, Math.min(7, Math.floor(width / 150)))
        columnSpacing: 12; rowSpacing: 12
        Repeater {
            model: audio.profiles
            delegate: Rectangle {
                id: pc
                required property var modelData
                readonly property bool sel: audio.profile === modelData.name
                Layout.fillWidth: true
                Layout.preferredHeight: 168
                radius: sel ? 40 : (pma2.pressed ? 20 : 28)
                color: sel ? Theme.primaryContainer : Theme.surfaceContainer
                Behavior on radius { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack } }
                Behavior on color { ColorAnimation { duration: Theme.medium } }
                scale: pma2.pressed ? 0.96 : 1
                Behavior on scale { NumberAnimation { duration: Theme.fast } }
                Rectangle { anchors.fill: parent; radius: parent.radius; color: Theme.ink; opacity: pma2.containsMouse && !pc.sel ? 0.05 : 0 }
                MorphShape {
                    x: 18; y: 18
                    width: pc.sel ? 64 : 52; height: width
                    Behavior on width { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack; easing.overshoot: 2 } }
                    shape: pc.modelData.shape
                    color: pc.sel ? Theme.primary : Theme.secondaryContainer
                    color2: pc.sel ? Theme.tertiary : Theme.secondaryContainer
                    spinning: pc.sel && audio.processing
                    Icon { anchors.centerIn: parent; name: page.profileIcons[pc.modelData.name] || "sparkle"; size: 24
                           color: pc.sel ? Theme.inkPrimary : Theme.inkSecondaryContainer }
                }
                Column {
                    anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                    anchors.margins: 18
                    spacing: 2
                    Label { text: pc.modelData.name; role: "titleM"; emphasized: true
                            color: pc.sel ? Theme.inkPrimaryContainer : Theme.ink }
                    Label { text: pc.modelData.desc; role: "bodyS"; width: parent.width; wrapMode: Text.WordWrap
                            lineHeightMode: Text.ProportionalHeight; lineHeight: 1.0; maximumLineCount: 2; elide: Text.ElideRight
                            color: pc.sel ? Theme.inkPrimaryContainer : Theme.inkVariant }
                }
                MouseArea { id: pma2; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: audio.applyProfile(pc.modelData.name) }
            }
        }
    }

    // ---------------------------------------------------------------- device
    RowLayout {
        width: parent.width
        spacing: 24
        Column {
            spacing: 2
            Label { text: "Listening on"; role: "titleL"; emphasized: true }
            Label { text: "Tunes crossfeed and bass for your hardware"; role: "body"; color: Theme.inkVariant }
        }
        ButtonGroup {
            Layout.fillWidth: true
            Layout.maximumWidth: 620
            Layout.alignment: Qt.AlignRight
            current: audio.deviceMode
            model: [{ key: "headphones", label: "Headphones", icon: "headphones" },
                    { key: "speakers", label: "Speakers", icon: "speakers" },
                    { key: "laptop", label: "Laptop", icon: "laptop" }]
            onPicked: (k) => audio.setDeviceMode(k)
        }
    }

    // ---------------------------------------------------------------- quick
    Label { text: "Quick tune"; role: "titleL"; emphasized: true; topPadding: 8 }
    GridLayout {
        width: parent.width
        columns: width > 900 ? 2 : 1
        columnSpacing: 16; rowSpacing: 16
        EffectCard {
            Layout.fillWidth: true
            title: "DeepBass"; subtitle: "Psychoacoustic bass you feel even on tiny speakers"
            icon: "bass"; shape: "cookie9"; toggleKey: "bass_on"
            ParamSlider { Layout.fillWidth: true; key: "bass_amt"; label: "Harmonic bass" }
        }
        EffectCard {
            Layout.fillWidth: true
            title: "Clarity"; subtitle: "Restores detail and air lost in compression"
            icon: "sparkle"; shape: "burst12"; toggleKey: "clar_on"
            ParamSlider { Layout.fillWidth: true; key: "clar_amt"; label: "Detail" }
        }
        EffectCard {
            Layout.fillWidth: true
            title: "3D Stage"; subtitle: "Pushes sound outside your head"
            icon: "space"; shape: "flower8"; toggleKey: "stage_on"
            ParamSlider { Layout.fillWidth: true; key: "stage_width"; label: "Width"; from: 0; to: 2
                          format: function(v) { return Math.round(v * 100) + "%" } }
        }
        EffectCard {
            Layout.fillWidth: true
            title: "Voice Focus"; subtitle: "Dialogue cuts through music and effects"
            icon: "mic"; shape: "pill"; toggleKey: "voice_on"
            ParamSlider { Layout.fillWidth: true; key: "voice_amt"; label: "Focus" }
        }
    }
}
