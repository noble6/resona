import QtQuick
import QtQuick.Layouts
import "../components"

Page {
    title: "Space"
    subtitle: "Spatial rendering: width, depth, room and headphone externalization"
    RowLayout {
        width: parent.width
        spacing: 20
        Card {
            Layout.preferredWidth: Math.min(560, parent.width * 0.48)
            Layout.fillHeight: true
            Layout.minimumHeight: 560
            color: Theme.surfaceContainerLow
            StageView { anchors.fill: parent; anchors.margins: 12 }
            Label { x: 28; y: 24; text: "Soundstage"; role: "titleM"; emphasized: true }
            Label { x: 28; y: 46; text: "Top-down view of what you hear"; role: "bodyS"; color: Theme.inkVariant }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 16
            EffectCard {
                Layout.fillWidth: true
                resetKeys: ["stage_on", "stage_width", "stage_depth"]
                title: "3D Stage"; subtitle: "Bass-safe widening + early reflections"
                icon: "space"; shape: "flower8"; toggleKey: "stage_on"
                ParamSlider { Layout.fillWidth: true; key: "stage_width"; label: "Width"; from: 0; to: 2
                              format: function(v) { return v < 0.05 ? "Mono" : Math.round(v * 100) + "%" } }
                ParamSlider { Layout.fillWidth: true; key: "stage_depth"; label: "Depth" }
            }
            EffectCard {
                id: hpCard
                Layout.fillWidth: true
                readonly property string mode: audio.params.hrtf_on ? "hrtf" : (audio.params.xfeed_on ? "xfeed" : "off")
                resetKeys: ["xfeed_on", "xfeed_amt", "hrtf_on", "hrtf_angle", "hrtf_amt"]
                title: "Headphone spatial"
                subtitle: mode === "hrtf" ? "Binaural virtual speakers with head-shadow, ITD and pinna cues"
                        : mode === "xfeed" ? "Crossfeed: speaker-like imaging, less fatigue" : "Off: direct stereo"
                icon: "headphones"; shape: "clover4"
                enabled: audio.outputLayout.channels <= 2
                ButtonGroup {
                    Layout.fillWidth: true
                    itemHeight: 48
                    current: hpCard.mode
                    model: [{ key: "off", label: "Off" }, { key: "xfeed", label: "Crossfeed" }, { key: "hrtf", label: "Spatial HRTF", icon: "space" }]
                    onPicked: (k) => audio.setHeadphoneSpatial(k)
                }
                ParamSlider { Layout.fillWidth: true; key: "xfeed_amt"; label: "Blend"; visible: !!audio.params.xfeed_on && !audio.params.hrtf_on }
                ParamSlider { Layout.fillWidth: true; key: "hrtf_angle"; label: "Speaker angle"; from: 15; to: 60; stepSize: 1
                              visible: !!audio.params.hrtf_on; format: function(v) { return "±" + Math.round(v) + "°" } }
                ParamSlider { Layout.fillWidth: true; key: "hrtf_amt"; label: "Externalization"; visible: !!audio.params.hrtf_on }
            }
            EffectCard {
                Layout.fillWidth: true
                resetKeys: ["amb_on", "amb_mix", "amb_size", "amb_damp"]
                title: "Ambience"; subtitle: "A real room around your music"
                icon: "room"; shape: "burst12"; toggleKey: "amb_on"
                ParamSlider { Layout.fillWidth: true; key: "amb_mix"; label: "Mix" }
                ParamSlider { Layout.fillWidth: true; key: "amb_size"; label: "Room size"
                              format: function(v) { return v < 0.33 ? "Studio" : v < 0.66 ? "Hall" : "Arena" } }
                ParamSlider { Layout.fillWidth: true; key: "amb_damp"; label: "Warmth" }
            }
        }
    }

    EffectCard {
        width: parent.width
        readonly property bool multi: audio.outputLayout.channels > 2
        resetKeys: ["upmix_on", "upmix_center", "upmix_surr", "upmix_lfe"]
        title: "Surround upmix"
        subtitle: multi ? "Stereo → " + audio.outputLayout.name + ": steered centre for dialogue, decorrelated surrounds, LFE"
                        : "Your output is stereo. Pick a 5.1, 7.1 or AC3 mode on the Hardware page to unlock"
        icon: "surround"; shape: "burst12"; toggleKey: multi ? "upmix_on" : ""
        enabled: multi
        RowLayout {
            Layout.fillWidth: true
            spacing: 32
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 14
                ParamSlider { Layout.fillWidth: true; key: "upmix_center"; label: "Centre (dialogue)" }
                ParamSlider { Layout.fillWidth: true; key: "upmix_surr"; label: "Surrounds" }
                ParamSlider { Layout.fillWidth: true; key: "upmix_lfe"; label: "Subwoofer (LFE)" }
            }
            Item {
                Layout.preferredWidth: 220; Layout.preferredHeight: 200
                readonly property var pos: ({ FL: [-0.6, -0.7], FR: [0.6, -0.7], FC: [0, -0.9], LFE: [0.35, -0.95],
                                              SL: [-0.95, 0.05], SR: [0.95, 0.05], RL: [-0.55, 0.85], RR: [0.55, 0.85] })
                Rectangle { anchors.centerIn: parent; width: 40; height: 48; radius: 20; color: Theme.surfaceContainerHighest
                            border.width: 2; border.color: Theme.outline }
                Repeater {
                    model: audio.outputLayout.positions
                    delegate: MorphShape {
                        required property string modelData
                        readonly property var p: parent.pos[modelData] || [0, 0]
                        width: modelData === "LFE" ? 30 : 34; height: width
                        x: parent.width / 2 + p[0] * 90 - width / 2; y: parent.height / 2 + p[1] * 90 - height / 2
                        shape: modelData === "LFE" ? "circle" : "cookie6"
                        color: Theme.primary; color2: Theme.tertiary
                        spinning: audio.processing
                        Label { anchors.centerIn: parent; text: modelData; role: "labelS"; emphasized: true; color: Theme.inkPrimary }
                    }
                }
            }
        }
    }
}
