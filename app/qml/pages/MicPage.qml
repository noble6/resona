import QtQuick
import QtQuick.Layouts
import "../components"

Page {
    id: page
    title: "Microphone"
    subtitle: "Clean, steady voice for calls, streams and games. Apps choose “Resona Microphone” as their input."
    readonly property var m: audio.mic.info
    readonly property var p: m.params || ({})
    readonly property var meters: audio.mic.meters
    readonly property int voice: Math.round(p.voice || 0)
    readonly property var voiceIcons: ["mic", "bass", "sparkle", "chip", "volume", "rocket", "room"]
    readonly property var voiceText: [
        "Your own voice, just cleaner",
        "Lower and bigger, like a movie trailer",
        "High and squeaky",
        "Metallic, ring-modulated robot",
        "Thin and crunchy, like an old walkie-talkie",
        "Wobbly pitch from another planet",
        "Your voice echoing around a cave"]

    component MicSlider: Column {
        id: ms
        property string key
        property string label
        property real from: 0
        property real to: 1
        property real stepSize: 0
        property bool bipolar: false
        property var format: function(v) { return Math.round((v - from) / (to - from) * 100) + "%" }
        readonly property real value: page.p[key] !== undefined ? page.p[key] : 0
        spacing: 2
        Item {
            width: parent.width; height: 20
            Label { text: ms.label; role: "labelL"; color: Theme.inkVariant; anchors.left: parent.left }
            Label { text: ms.format(ms.value); role: "labelL"; emphasized: true; anchors.right: parent.right }
        }
        WavySlider {
            width: parent.width
            from: ms.from; to: ms.to; stepSize: ms.stepSize; bipolar: ms.bipolar
            value: ms.value; format: ms.format
            animated: page.m.active === true
            Accessible.name: ms.label
            onMoved: (v) => audio.mic.setParam(ms.key, v)
        }
    }

    component MicCard: Card {
        id: mc
        property string title
        property string subtitle
        property string icon
        property string shape: "cookie9"
        property bool lit: true
        default property alias content: body.data
        implicitHeight: col.implicitHeight + 2 * pad
        color: lit ? Theme.surfaceContainer : Theme.surfaceContainerLow
        ColumnLayout {
            id: col
            anchors.fill: parent; anchors.margins: mc.pad
            spacing: 16
            RowLayout {
                spacing: 16
                Layout.fillWidth: true
                MorphShape {
                    width: 52; height: 52; Layout.preferredWidth: 52; Layout.preferredHeight: 52
                    shape: mc.lit ? mc.shape : "circle"
                    color: mc.lit ? Theme.primaryContainer : Theme.surfaceContainerHighest
                    color2: mc.lit ? Theme.tertiaryContainer : Theme.surfaceContainerHighest
                    spinning: mc.lit && page.m.active === true
                    spinDuration: 16000
                    Icon { anchors.centerIn: parent; name: mc.icon; size: 24
                           color: mc.lit ? Theme.inkPrimaryContainer : Theme.inkVariant }
                }
                ColumnLayout {
                    spacing: 0; Layout.fillWidth: true
                    Label { text: mc.title; role: "titleL"; emphasized: true }
                    Label { text: mc.subtitle; role: "body"; color: Theme.inkVariant; Layout.fillWidth: true; elide: Text.ElideRight }
                }
            }
            ColumnLayout { id: body; Layout.fillWidth: true; spacing: 14 }
        }
    }

    component LiveValue: Rectangle {
        property string label
        property string value
        Layout.fillWidth: true
        height: 48; radius: 24
        color: Theme.surfaceContainerHigh
        Label { text: parent.label; role: "labelL"; color: Theme.inkVariant
                anchors.left: parent.left; anchors.leftMargin: 20; anchors.verticalCenter: parent.verticalCenter }
        Label { text: parent.value; role: "titleM"; emphasized: true; color: Theme.primary
                anchors.right: parent.right; anchors.rightMargin: 20; anchors.verticalCenter: parent.verticalCenter }
    }

    headerRight: [
        Btn {
            text: page.m.test === "recording" ? "Recording… speak now"
                : page.m.test === "playing" ? "Playing back…" : "Test my voice"
            icon: page.m.test === "idle" ? "mic" : "waves"
            variant: "tonal"
            enabled: page.m.running === true && page.m.test === "idle"
            opacity: enabled || page.m.test !== "idle" ? 1 : 0.5
            onClicked: audio.mic.test()
        },
        Btn {
            icon: "reset"; variant: "text"; size: 40
            Accessible.name: "Reset microphone settings"
            onClicked: audio.mic.reset()
        }
    ]

    // ------------------------------------------------------------------ hero
    Rectangle {
        width: parent.width
        height: heroRow.implicitHeight + 64
        radius: 44
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.mix(Theme.primaryContainer, Theme.surfaceContainer, page.m.on ? 0.15 : 0.85) }
            GradientStop { position: 0.6; color: Theme.surfaceContainer }
            GradientStop { position: 1; color: Theme.mix(Theme.tertiaryContainer, Theme.surfaceContainer, 0.6) }
        }
        RowLayout {
            id: heroRow
            anchors.fill: parent; anchors.margins: 32
            spacing: 36
            Item {
                Layout.preferredWidth: 180; Layout.preferredHeight: 196
                MorphShape {
                    id: power
                    width: 150; height: 150
                    anchors.horizontalCenter: parent.horizontalCenter
                    shape: page.m.on ? "cookie12" : "circle"
                    color: page.m.on ? Theme.primary : Theme.surfaceContainerHighest
                    color2: page.m.on ? Theme.tertiary : Theme.surfaceContainerHighest
                    spinning: page.m.active === true
                    spinDuration: 9000
                    scale: pma.pressed ? 0.92 : (pma.containsMouse ? 1.04 : 1)
                    Behavior on scale { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack } }
                    Icon { anchors.centerIn: parent; name: "mic"; size: 54
                           color: page.m.on ? Theme.inkPrimary : Theme.inkVariant }
                    MouseArea { id: pma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: audio.mic.setOn(!page.m.on) }
                    activeFocusOnTab: true
                    Accessible.role: Accessible.CheckBox
                    Accessible.name: "Resona Microphone"
                    Accessible.checked: page.m.on === true
                    Keys.onPressed: (e) => { if (e.key === Qt.Key_Space || e.key === Qt.Key_Return) { audio.mic.setOn(!page.m.on); e.accepted = true } }
                    FocusRing { radius: 75 }
                }
                Label { anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom
                        text: page.m.on ? "Microphone on" : "Microphone off"; role: "titleM"; emphasized: true }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 14
                Label { text: "NOW"; role: "labelL"; color: Theme.primary; font.letterSpacing: 2 }
                Label { text: page.m.status || "Off"; role: "headlineM"; emphasized: true
                        Layout.fillWidth: true; elide: Text.ElideRight }
                RowLayout {
                    Layout.fillWidth: true; spacing: 14
                    Label { text: "Input"; role: "labelL"; color: Theme.inkVariant }
                    SelectButton {
                        readonly property var srcs: audio.mic.sources
                        options: ["System default"].concat(srcs.map(s => s.description))
                        current: page.m.chosen ? (srcs.find(s => s.name === page.m.chosen) || { description: page.m.chosen }).description
                                               : "System default"
                        placeholder: "Microphone"
                        onPicked: (v) => {
                            const i = options.indexOf(v)
                            audio.mic.setSource(i <= 0 ? "" : srcs[i - 1].name)
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Label { text: "Use as default microphone"; role: "labelL"; color: Theme.inkVariant }
                    M3Switch { checked: page.m.makeDefault === true; Accessible.name: "Use as default microphone"
                               onToggled: (v) => audio.mic.setMakeDefault(v) }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2; columnSpacing: 14; rowSpacing: 10
                    Label { text: "In"; role: "labelL"; color: Theme.inkVariant }
                    LevelBar { Layout.fillWidth: true; value: page.meters.in || 0 }
                    Label { text: "Out"; role: "labelL"; color: Theme.inkVariant }
                    LevelBar { Layout.fillWidth: true; value: page.meters.out || 0; accent: true }
                }
                Label {
                    visible: page.m.on && page.m.active !== true
                    text: "Levels move while an app records from Resona Microphone, or while you test your voice."
                    role: "body"; color: Theme.inkVariant; Layout.fillWidth: true; wrapMode: Text.WordWrap
                }
            }
        }
    }

    component LevelBar: Rectangle {
        property real value: 0
        property bool accent: false
        height: 12; radius: 6
        color: Theme.surfaceContainerHighest
        Rectangle {
            height: parent.height; radius: 6
            width: parent.width * Math.max(0, Math.min(1, parent.value))
            Behavior on width { NumberAnimation { duration: 90 } }
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: Theme.primary }
                GradientStop { position: 1; color: parent.parent.accent ? Theme.tertiary : Theme.secondary }
            }
        }
    }

    // ------------------------------------------------------------------ cleanup
    Label { text: "Clean up"; role: "titleL"; emphasized: true; topPadding: 8 }
    GridLayout {
        width: parent.width
        columns: width > 900 ? 3 : 1
        columnSpacing: 16; rowSpacing: 16
        MicCard {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 1
            title: "Noise suppression"; subtitle: "Fans, hum, hiss and keyboard noise fade away"
            icon: "shield"; shape: "cookie9"; lit: (page.p.ns || 0) > 0.001
            MicSlider { Layout.fillWidth: true; key: "ns"; label: "Strength"
                        format: function(v) { return v < 0.005 ? "Off" : Math.round(v * 100) + "%" } }
            LiveValue { label: "Removing now"; value: (page.meters.nr || 0).toFixed(1) + " dB" }
        }
        MicCard {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 1
            title: "Voice clarity"; subtitle: "Presence and air, less boom and mud"
            icon: "sparkle"; shape: "burst12"; lit: (page.p.clarity || 0) > 0.001
            MicSlider { Layout.fillWidth: true; key: "clarity"; label: "Clarity" }
            RowLayout {
                Layout.fillWidth: true
                Label { text: "Rumble filter (below 80 Hz)"; role: "bodyL"; Layout.fillWidth: true }
                M3Switch { checked: (page.p.hpf || 0) >= 0.5; Accessible.name: "Rumble filter"
                           onToggled: (v) => audio.mic.setParam("hpf", v ? 1 : 0) }
            }
        }
        MicCard {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 1
            title: "Auto level"; subtitle: "Same loudness whether you whisper or shout"
            icon: "speed"; shape: "flower8"; lit: (page.p.agc || 0) >= 0.5
            RowLayout {
                Layout.fillWidth: true
                Label { text: "Auto level"; role: "bodyL"; Layout.fillWidth: true }
                M3Switch { checked: (page.p.agc || 0) >= 0.5; Accessible.name: "Auto level"
                           onToggled: (v) => audio.mic.setParam("agc", v ? 1 : 0) }
            }
            MicSlider { Layout.fillWidth: true; key: "agc_target"; label: "Target loudness"; from: -30; to: -10; stepSize: 1
                        format: function(v) { return Math.round(v) + " dB" } }
            MicSlider { Layout.fillWidth: true; key: "gain"; label: "Input boost"; from: -12; to: 24; stepSize: 0.5; bipolar: true
                        format: function(v) { return (v > 0 ? "+" : "") + v.toFixed(1) + " dB" } }
        }
    }

    // ------------------------------------------------------------------ voice changer
    MicCard {
        width: parent.width
        title: "Voice changer"; subtitle: "For fun: everyone listening to Resona Microphone hears it live"
        icon: "rocket"; shape: "clover4"; lit: page.voice > 0
        ButtonGroup {
            Layout.fillWidth: true
            itemHeight: 48
            current: audio.mic.voices[page.voice] || "Off"
            model: audio.mic.voices.map((v, i) => ({ key: v, label: v, icon: page.voiceIcons[i] }))
            onPicked: (k) => audio.mic.setVoice(audio.mic.voices.indexOf(k))
        }
        Label { text: page.voiceText[page.voice] || ""; role: "body"; color: Theme.inkVariant; Layout.fillWidth: true }
        MicSlider {
            visible: [1, 2, 5].indexOf(page.voice) >= 0
            Layout.fillWidth: true; key: "pitch"; label: "Pitch"; from: -12; to: 12; stepSize: 1; bipolar: true
            format: function(v) { return (v > 0 ? "+" : "") + Math.round(v) + " semitones" }
        }
    }
}
