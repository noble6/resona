import QtQuick
import QtQuick.Layouts
import "../components"

Page {
    title: "Dynamics"
    subtitle: "Consistent loudness at any volume, without clipping"
    RowLayout {
        width: parent.width
        spacing: 20
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 16
            EffectCard {
                Layout.fillWidth: true
                title: "Smart Leveler"; subtitle: "No more volume jumps between songs, ads and scenes"
                icon: "speed"; shape: "cookie9"; toggleKey: "lev_on"
                ParamSlider { Layout.fillWidth: true; key: "lev_amt"; label: "Strength" }
                ParamSlider { Layout.fillWidth: true; key: "lev_target"; label: "Target loudness"; from: -30; to: -6; stepSize: 1
                              format: function(v) { return v.toFixed(0) + " dB" } }
                LiveValue { label: "Applied gain"; value: audio.meters.leveler; unit: "dB"; signed: true }
            }
            EffectCard {
                Layout.fillWidth: true
                title: "Adaptive Loudness"; subtitle: "Full bass and treble even when the volume is low"
                icon: "volume"; shape: "flower8"; toggleKey: "loud_on"
                ParamSlider { Layout.fillWidth: true; key: "loud_amt"; label: "Compensation" }
                LiveValue { label: "Bass compensation now"; value: audio.meters.loudness; unit: "dB"; signed: true }
            }
            EffectCard {
                Layout.fillWidth: true
                title: "Limiter"; subtitle: "Lookahead brickwall — protects ears and speakers"
                icon: "shield"; shape: "gem"; toggleKey: "lim_on"
                ParamSlider { Layout.fillWidth: true; key: "lim_ceil"; label: "Ceiling"; from: -6; to: 0; stepSize: 0.1
                              format: function(v) { return v.toFixed(1) + " dBFS" } }
                LiveValue { label: "Gain reduction"; value: audio.meters.limiter; unit: "dB"; signed: false }
            }
        }
        Card {
            Layout.preferredWidth: 300
            Layout.fillHeight: true
            color: Theme.surfaceContainerLow
            Column {
                anchors.fill: parent; anchors.margins: 28
                spacing: 6
                Label { text: "Levels"; role: "titleL"; emphasized: true }
                Label { text: "Peak, before → after"; role: "body"; color: Theme.inkVariant }
            }
            Row {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: 20
                spacing: 40
                Repeater {
                    model: [["IN", "in"], ["OUT", "out"]]
                    delegate: Column {
                        required property var modelData
                        spacing: 12
                        Meter { width: 56; height: 380; value: audio.meters[modelData[1]] || 0 }
                        Label { text: modelData[0]; role: "labelL"; emphasized: true; anchors.horizontalCenter: parent.horizontalCenter
                                color: Theme.inkVariant }
                    }
                }
            }
        }
    }
    component LiveValue: Rectangle {
        property string label
        property real value
        property string unit
        property bool signed: true
        Layout.fillWidth: true
        height: 48; radius: 24
        color: Theme.surfaceContainerHigh
        Label { anchors.left: parent.left; anchors.leftMargin: 20; anchors.verticalCenter: parent.verticalCenter
                text: parent.label; role: "labelL"; color: Theme.inkVariant }
        Label { anchors.right: parent.right; anchors.rightMargin: 20; anchors.verticalCenter: parent.verticalCenter
                text: (parent.signed && parent.value > 0 ? "+" : "") + parent.value.toFixed(1) + " " + parent.unit
                role: "titleM"; emphasized: true; color: Theme.primary
                font.features: { "tnum": 1 } }
    }

    EffectCard {
        width: parent.width
        title: "Tube Warmth"; subtitle: "Analog even-harmonic saturation — the glow of a valve amp"
        icon: "fire"; shape: "cookie6"; toggleKey: "tube_on"
        ParamSlider { Layout.fillWidth: true; key: "tube_drive"; label: "Drive" }
    }
}
