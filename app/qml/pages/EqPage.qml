import QtQuick
import QtQuick.Layouts
import "../components"

Page {
    id: page
    title: "Equalizer"
    subtitle: "Drag the points. Double-click to zero a band. Scroll for fine steps."
    headerRight: [
        Row {
            spacing: 12
            Label { text: "EQ"; role: "titleM"; anchors.verticalCenter: parent.verticalCenter }
            M3Switch { Accessible.name: "Equalizer"; checked: !!audio.params.eq_on; onToggled: (v) => audio.setParam("eq_on", v ? 1 : 0)
                       anchors.verticalCenter: parent.verticalCenter }
        },
        Btn { text: "Reset"; icon: "reset"; variant: "outlined"; onClicked: audio.resetEq() }
    ]

    Flow {
        width: parent.width
        spacing: 8
        Repeater {
            model: audio.eqPresets
            delegate: Chip {
                required property string modelData
                text: modelData
                selected: audio.eqPreset === modelData && !audio.modified
                onClicked: audio.applyEq(modelData)
            }
        }
    }

    Card {
        width: parent.width
        height: 470
        opacity: audio.params.eq_on ? 1 : 0.45
        Behavior on opacity { NumberAnimation { duration: Theme.fast } }
        EqGraph {
            id: graph
            anchors.fill: parent
            anchors.margins: 28
            anchors.bottomMargin: 56
        }
        Repeater {
            model: audio.eqFreqs
            delegate: Label {
                required property var modelData
                x: 28 + graph.fx(modelData) - width / 2
                y: parent.height - 44
                text: modelData >= 1000 ? (modelData / 1000) + "k" : modelData
                role: "labelL"; color: Theme.inkVariant
            }
        }
    }

    GridLayout {
        width: parent.width
        columns: 2; columnSpacing: 16
        EffectCard {
            Layout.fillWidth: true
            title: "Preamp"; subtitle: "Headroom before the effects chain"
            icon: "volume"; shape: "cookie6"
            ParamSlider { Layout.fillWidth: true; key: "preamp"; label: "Gain"; from: -12; to: 12; bipolar: true; stepSize: 0.5
                          format: function(v) { return (v > 0 ? "+" : "") + v.toFixed(1) + " dB" } }
        }
        EffectCard {
            Layout.fillWidth: true
            title: "Output"; subtitle: "Final level after all processing"
            icon: "speakers"; shape: "gem"
            ParamSlider { Layout.fillWidth: true; key: "output"; label: "Gain"; from: -12; to: 12; bipolar: true; stepSize: 0.5
                          format: function(v) { return (v > 0 ? "+" : "") + v.toFixed(1) + " dB" } }
        }
    }

    EffectCard {
        width: parent.width
        title: "Intelligent EQ"; subtitle: "Listens to what's playing and steers the tonal balance, song by song and scene by scene"
        icon: "sparkle"; shape: "sunny"; toggleKey: "ieq_on"
        RowLayout {
            Layout.fillWidth: true
            spacing: 32
            ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 1
                spacing: 14
                ButtonGroup {
                    Layout.fillWidth: true
                    itemHeight: 48
                    current: audio.ieqTargets[Math.round(audio.params.ieq_target || 0)]
                    model: audio.ieqTargets.map(t => ({ key: t, label: t }))
                    onPicked: (k) => audio.setParam("ieq_target", audio.ieqTargets.indexOf(k))
                }
                ParamSlider { Layout.fillWidth: true; key: "ieq_amt"; label: "Strength" }
            }
            Column {
                Layout.fillWidth: true; Layout.preferredWidth: 1
                spacing: 6
                Label { text: "Live correction"; role: "labelL"; color: Theme.inkVariant }
                IeqBars { width: parent.width; gains: audio.meters.ieq || [] }
            }
        }
    }
}
