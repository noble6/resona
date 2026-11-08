import QtQuick
import QtQuick.Layouts
import "../components"

Page {
    id: page
    title: "Hardware"
    subtitle: "Every card, codec, connector and format on this machine"
    readonly property var kindIcon: ({ stereo: "speakers", surround: "surround", hdmi: "hdmi", optical: "light",
                                       encoded: "movie", pro: "tune", bluetooth: "bluetooth" })
    readonly property var kindLabel: ({ stereo: "Stereo", surround: "Surround", hdmi: "HDMI / DisplayPort",
                                        optical: "S/PDIF optical", encoded: "Dolby Digital encode (AC3)",
                                        pro: "Pro audio", bluetooth: "Bluetooth" })
    readonly property var busIcon: ({ pci: "chip", usb: "usb", bluetooth: "bluetooth" })
    function fmtRate(r) { return r >= 1000 ? (r / 1000).toFixed(r % 1000 ? 1 : 0) + " kHz" : r + " Hz" }
    headerRight: [ Btn { text: "Rescan"; icon: "reset"; variant: "outlined"; onClicked: audio.refreshHardware() } ]

    // ------------------------------------------------ Hi-Res
    Rectangle {
        width: parent.width
        height: hiresCol.implicitHeight + 56
        radius: 40
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.mix(Theme.primaryContainer, Theme.surfaceContainer, audio.hiRes ? 0.1 : 0.7) }
            GradientStop { position: 1; color: Theme.surfaceContainer }
        }
        ColumnLayout {
            id: hiresCol
            anchors.fill: parent; anchors.margins: 28
            spacing: 16
            RowLayout {
                spacing: 18
                MorphShape { width: 72; height: 72; Layout.preferredWidth: 72; Layout.preferredHeight: 72
                             shape: audio.hiRes ? "burst12" : "cookie6"; spinning: audio.hiRes
                             color: audio.hiRes ? Theme.primary : Theme.surfaceContainerHighest
                             color2: audio.hiRes ? Theme.tertiary : Theme.surfaceContainerHighest
                             Label { anchors.centerIn: parent; text: "HR"; role: "titleL"; emphasized: true
                                     color: audio.hiRes ? Theme.inkPrimary : Theme.inkVariant } }
                Column { Layout.fillWidth: true; spacing: 2
                    Label { text: "Hi-Res Audio"; role: "headlineS"; emphasized: true }
                    Label { width: parent.width; wrapMode: Text.WordWrap; role: "body"; color: Theme.inkVariant
                            text: audio.hiRes ? "PipeWire follows each song's native rate — 44.1, 96, 192 kHz… no resampling to 48 kHz."
                                              : "Off: every stream is resampled to " + page.fmtRate(+(audio.clock.rate || 48000)) + ". Turn on to play files at their native rate." } }
                M3Switch { checked: audio.hiRes; onToggled: (v) => audio.setHiRes(v) }
            }
            Flow {
                Layout.fillWidth: true; spacing: 8
                Repeater {
                    model: [
                        ["Clock now", page.fmtRate(+(audio.clock.rate || 48000))],
                        ["Allowed", (audio.clock["allowed-rates"] || "[ 48000 ]").replace(/[\[\]]/g, "").trim().split(/\s+/).map(r => (r / 1000) + "k").join(" · ")],
                        ["Buffer", (audio.clock.quantum || 1024) + " samples · " + ((audio.clock.quantum || 1024) / (+(audio.clock.rate || 48000)) * 1000).toFixed(1) + " ms"],
                        ["Engine", (audio.sampleRate / 1000) + " kHz · " + audio.outputLayout.name + " · 32-bit float"]
                    ]
                    delegate: Rectangle {
                        required property var modelData
                        height: 40; radius: 20; width: rr.implicitWidth + 28
                        color: Theme.surfaceContainerHighest
                        Row { id: rr; anchors.centerIn: parent; spacing: 8
                            Label { text: modelData[0]; role: "labelL"; color: Theme.inkVariant }
                            Label { text: modelData[1]; role: "labelL"; emphasized: true } }
                    }
                }
            }
            RowLayout {
                spacing: 12
                Column { Layout.fillWidth: true
                    Label { text: "Studio-grade resampler"; role: "titleM"; emphasized: true }
                    Label { text: "Highest-quality sample-rate conversion for every app (applies after an audio restart)"
                            role: "body"; color: Theme.inkVariant } }
                M3Switch { checked: audio.hqResampler; onToggled: (v) => audio.setHqResampler(v) }
                Btn { text: "Restart audio"; icon: "reset"; variant: "tonal"; onClicked: audio.restartAudio() }
            }
        }
    }

    // ------------------------------------------------ cards
    Repeater {
        model: audio.hardware
        delegate: Card {
            id: card
            required property var modelData
            width: page.width - 80
            height: cardCol.implicitHeight + 56
            ColumnLayout {
                id: cardCol
                anchors.fill: parent; anchors.margins: 28
                spacing: 16
                RowLayout {
                    spacing: 16
                    MorphShape { width: 56; height: 56; Layout.preferredWidth: 56; Layout.preferredHeight: 56
                                 shape: "cookie9"; color: Theme.secondaryContainer
                                 Icon { anchors.centerIn: parent; name: page.busIcon[card.modelData.bus] || "chip"; color: Theme.inkSecondaryContainer } }
                    Column { Layout.fillWidth: true
                        Label { text: card.modelData.title; role: "titleL"; emphasized: true; width: parent.width; elide: Text.ElideRight }
                        Label { text: [card.modelData.vendor, card.modelData.driver].filter(x => x).join(" · "); role: "body"; color: Theme.inkVariant } }
                    Rectangle {
                        visible: !!card.modelData.codec
                        height: 36; radius: 18; width: cc.implicitWidth + 28; color: Theme.tertiaryContainer
                        Row { id: cc; anchors.centerIn: parent; spacing: 6
                            Icon { name: "chip"; size: 18; color: Theme.inkTertiaryContainer; anchors.verticalCenter: parent.verticalCenter }
                            Label { text: card.modelData.codec; role: "labelL"; emphasized: true; color: Theme.inkTertiaryContainer } }
                    }
                }
                // outputs with capabilities
                Repeater {
                    model: card.modelData.sinks
                    delegate: Rectangle {
                        id: sk
                        required property var modelData
                        Layout.fillWidth: true
                        height: skRow.implicitHeight + 28; radius: 20
                        color: audio.output === modelData.name ? Theme.secondaryContainer : Theme.surfaceContainerHigh
                        RowLayout {
                            id: skRow
                            anchors.fill: parent; anchors.margins: 14; anchors.leftMargin: 20
                            spacing: 10
                            Column { Layout.fillWidth: true
                                Label { text: sk.modelData.description; role: "bodyL"; emphasized: audio.output === sk.modelData.name
                                        width: parent.width; elide: Text.ElideRight }
                                Label { role: "bodyS"; color: Theme.inkVariant
                                        text: sk.modelData.layout + " · " + (sk.modelData.bits ? sk.modelData.bits + "-bit · " : "")
                                              + (sk.modelData.rates.length ? "up to " + page.fmtRate(sk.modelData.maxRate) : "")
                                              + (sk.modelData.btCodec ? " · " + sk.modelData.btCodec.toUpperCase() : "") }
                            }
                            Rectangle { visible: sk.modelData.hires; height: 28; radius: 14; width: hrl.implicitWidth + 20; color: Theme.primary
                                        Label { id: hrl; anchors.centerIn: parent; text: "Hi-Res"; role: "label"; emphasized: true; color: Theme.inkPrimary } }
                            Btn { visible: audio.output !== sk.modelData.name; text: "Use"; variant: "text"; size: 32
                                  onClicked: audio.setOutput(sk.modelData.name) }
                            Label { visible: audio.output === sk.modelData.name; text: "Resona plays here"; role: "labelL"; color: Theme.primary }
                        }
                    }
                }
                // displays (HDMI ELD)
                Repeater {
                    model: card.modelData.displays
                    delegate: Row {
                        required property var modelData
                        spacing: 10
                        Icon { name: "hdmi"; size: 20; color: Theme.inkVariant; anchors.verticalCenter: parent.verticalCenter }
                        Label { anchors.verticalCenter: parent.verticalCenter; role: "body"
                                text: modelData.name + " accepts " + modelData.formats.map(f => f.coding + " " + f.channels + "ch"
                                      + (f.bits ? " " + f.bits + "-bit" : "") + (f.maxRate ? " " + (f.maxRate / 1000) + "k" : "")).join(", ") }
                    }
                }
                // connectors
                Flow {
                    Layout.fillWidth: true; spacing: 8
                    visible: card.modelData.ports.length > 0
                    Repeater {
                        model: card.modelData.ports
                        delegate: Rectangle {
                            required property var modelData
                            height: 32; radius: 16; width: pr.implicitWidth + 24
                            color: "transparent"; border.width: 1; border.color: Theme.outlineVariant
                            Row { id: pr; anchors.centerIn: parent; spacing: 8
                                Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter
                                            color: modelData.plugged ? "#4ADE80" : (modelData.available ? Theme.outline : Theme.outlineVariant) }
                                Label { text: modelData.description + (modelData.plugged ? " · connected" : ""); role: "labelL"
                                        color: modelData.available ? Theme.ink : Theme.inkVariant } }
                        }
                    }
                }
                // output modes
                Label { text: "Output mode"; role: "titleM"; emphasized: true; visible: card.modelData.profiles.length > 0 }
                Flow {
                    Layout.fillWidth: true; spacing: 8
                    Repeater {
                        model: card.modelData.profiles.filter(p => p.kind !== "pro" && p.name.indexOf("+input") < 0)
                        delegate: Chip {
                            required property var modelData
                            text: modelData.description.replace(" Output", "")
                            icon: page.kindIcon[modelData.kind] || "speakers"
                            selected: card.modelData.activeProfile === modelData.name
                                      || card.modelData.activeProfile === modelData.name + "+input:analog-stereo"
                            opacity: modelData.available ? 1 : 0.4
                            onClicked: if (modelData.available) audio.setCardProfile(card.modelData.name, modelData.name)
                        }
                    }
                }
                // Bluetooth codecs
                Flow {
                    id: btFlow
                    visible: card.modelData.bluetooth
                    Layout.fillWidth: true; spacing: 8
                    property var codecs: []
                    Component.onCompleted: if (card.modelData.bluetooth) codecs = audio.btCodecs(card.modelData.name)
                    Label { text: "Codec"; role: "titleM"; emphasized: true; height: 36; verticalAlignment: Text.AlignVCenter }
                    Repeater {
                        model: btFlow.codecs
                        delegate: Chip { required property string modelData; text: modelData.toUpperCase()
                                         selected: card.modelData.sinks.some(s => s.btCodec === modelData)
                                         onClicked: audio.setBtCodec(card.modelData.name, modelData) }
                    }
                }
            }
        }
    }
}
