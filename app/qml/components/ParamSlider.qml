import QtQuick

// Labeled slider bound to an engine parameter.
Column {
    id: root
    property string key
    property string label
    property real from: 0
    property real to: 1
    property real stepSize: 0
    property bool bipolar: false
    property var format: function(v) { return Math.round((v - from) / (to - from) * 100) + "%" }
    readonly property real value: audio.params[key] !== undefined ? audio.params[key] : 0
    spacing: 2
    Item {
        width: parent.width; height: 20
        Label { text: root.label; role: "labelL"; color: Theme.inkVariant; anchors.left: parent.left }
        Label { text: root.format(root.value); role: "labelL"; color: Theme.ink; anchors.right: parent.right; emphasized: true }
    }
    WavySlider {
        Accessible.name: root.label
        width: parent.width
        from: root.from; to: root.to; stepSize: root.stepSize; bipolar: root.bipolar
        value: root.value
        format: root.format
        enabled: root.enabled
        onMoved: (v) => audio.setParam(root.key, v)
    }
}
