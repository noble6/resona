import QtQuick
import QtQuick.Shapes

// M3 Expressive slider: wavy active track (animated while audio flows),
// flat inactive track, tall pill handle that squeezes on press, value bubble.
Item {
    id: root
    property real from: 0
    property real to: 1
    property real value: 0.5
    property real stepSize: 0
    property bool bipolar: false          // fill from the centre (gain sliders)
    property bool wavy: true
    property bool animated: audio ? audio.processing : false
    property var format: function(v) { return Math.round((v - from) / (to - from) * 100) + "%" }
    property color activeColor: Theme.primary
    property color trackColor: Theme.secondaryContainer
    signal moved(real value)

    implicitHeight: 44
    implicitWidth: 240
    opacity: enabled ? 1 : 0.38
    Behavior on opacity { NumberAnimation { duration: Theme.fast } }

    readonly property real frac: Math.max(0, Math.min(1, (value - from) / (to - from)))
    readonly property real zeroFrac: bipolar ? Math.max(0, Math.min(1, (0 - from) / (to - from))) : 0
    readonly property real handleX: frac * (width - 4) + 2
    readonly property real gap: 6
    property real amp: (wavy && enabled && Math.abs(frac - zeroFrac) > 0.02) ? (mouse.pressed ? 2 : 3.2) : 0
    Behavior on amp { NumberAnimation { duration: 320; easing.type: Easing.OutBack } }
    readonly property real wavelength: 26

    // inactive track
    Rectangle {
        readonly property real x0: root.bipolar ? 0 : root.handleX + root.gap
        x: x0; width: Math.max(0, root.width - x0)
        anchors.verticalCenter: parent.verticalCenter
        height: 6; radius: 3
        color: root.trackColor
    }
    // stop indicator
    Rectangle {
        width: 4; height: 4; radius: 2
        x: root.width - 7; anchors.verticalCenter: parent.verticalCenter
        color: root.activeColor
        visible: root.frac < 0.97
    }
    // active (wavy) track: path spans exactly the active range; phase scrolls the sine
    Shape {
        id: wave
        readonly property real a: root.bipolar ? Math.min(root.zeroFrac, root.frac) * (root.width - 4) + 2 : 0
        readonly property real b: root.bipolar ? Math.max(root.zeroFrac, root.frac) * (root.width - 4) + 2 : root.handleX
        readonly property bool handleOnRight: !root.bipolar || root.frac >= root.zeroFrac
        readonly property real x0: a + (handleOnRight ? 0 : root.gap) + 3
        readonly property real x1: b - (handleOnRight ? root.gap : 0) - 3
        property real phase: 0
        anchors.fill: parent
        visible: x1 > x0
        preferredRendererType: Shape.GeometryRenderer
        NumberAnimation on phase {
            from: 0; to: Math.PI * 2; duration: 900
            loops: Animation.Infinite; running: root.animated && root.amp > 0.05 && root.visible
        }
        ShapePath {
            strokeColor: root.activeColor
            strokeWidth: 6
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            fillColor: "transparent"
            PathPolyline {
                path: {
                    const pts = [], cy = root.height / 2, amp = root.amp, k = Math.PI * 2 / root.wavelength
                    const x0 = wave.x0, x1 = wave.x1, ph = wave.phase
                    if (x1 <= x0) return [Qt.point(0, cy), Qt.point(0, cy)]
                    const step = amp > 0.05 ? 2 : (x1 - x0)
                    for (let x = x0; x < x1; x += step) pts.push(Qt.point(x, cy + amp * Math.sin(x * k - ph)))
                    pts.push(Qt.point(x1, cy + amp * Math.sin(x1 * k - ph)))
                    return pts
                }
            }
        }
    }
    // handle
    Rectangle {
        id: handle
        width: mouse.pressed ? 2 : 4
        height: mouse.pressed ? 40 : 44
        radius: width / 2
        x: root.handleX - width / 2
        anchors.verticalCenter: parent.verticalCenter
        color: root.activeColor
        Behavior on width { NumberAnimation { duration: Theme.fast } }
        Behavior on height { NumberAnimation { duration: Theme.fast } }
    }
    // value bubble
    Rectangle {
        id: bubble
        readonly property bool show: mouse.pressed || mouse.containsMouse && hoverTimer.done
        width: Math.max(48, bubbleText.implicitWidth + 24); height: 40; radius: 20
        color: Theme.inverseSurface
        x: Math.max(-8, Math.min(root.width - width + 8, root.handleX - width / 2))
        y: -height - 6
        opacity: show ? 1 : 0
        scale: show ? 1 : 0.6
        transformOrigin: Item.Bottom
        Behavior on opacity { NumberAnimation { duration: Theme.fast } }
        Behavior on scale { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack } }
        Text {
            id: bubbleText
            anchors.centerIn: parent
            text: root.format(root.value)
            color: Theme.inverseOnSurface
            font.family: Theme.font; font.pixelSize: 14; font.weight: Font.DemiBold
        }
    }
    Timer { id: hoverTimer; property bool done: false; interval: 400; running: mouse.containsMouse; onRunningChanged: if (!running) done = false; onTriggered: done = true }

    function setFromX(x) {
        let f = Math.max(0, Math.min(1, (x - 2) / (width - 4)))
        let v = from + f * (to - from)
        if (stepSize > 0) v = Math.round(v / stepSize) * stepSize
        if (bipolar && Math.abs(v) < (to - from) * 0.015) v = 0    // detent at zero
        v = Math.max(from, Math.min(to, v))
        if (v !== value) moved(v)
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        anchors.topMargin: -4; anchors.bottomMargin: -4
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        preventStealing: true
        onPressed: (e) => root.setFromX(e.x)
        onPositionChanged: (e) => { if (pressed) root.setFromX(e.x) }
        onWheel: (w) => {
            const step = root.stepSize > 0 ? root.stepSize : (root.to - root.from) / 50
            let v = root.value + (w.angleDelta.y > 0 ? step : -step)
            root.moved(Math.max(root.from, Math.min(root.to, v)))
        }
        onDoubleClicked: if (root.bipolar) root.moved(0)
    }
}
