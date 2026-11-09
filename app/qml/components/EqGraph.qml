import QtQuick

// Interactive 10-band EQ: drag handles, live response curve, spectrum underlay.
Item {
    id: root
    readonly property var freqs: audio.eqFreqs
    // The curve is the true summed response: boosted neighbours add up past any single band,
    // so the scale grows to fit it (frozen while dragging so the handle tracks the pointer)
    property int dragging: 0
    readonly property real fitRange: {
        let m = 0
        for (const v of audio.eqCurve) m = Math.max(m, Math.abs(v))
        return Math.max(15, Math.ceil((m + 2) / 6) * 6)
    }
    property real range: 15
    Binding on range { value: root.fitRange; when: root.dragging === 0; restoreMode: Binding.RestoreNone }
    Behavior on range { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
    onRangeChanged: { grid.requestPaint(); curve.requestPaint() }
    function curveAt(f) {
        const pts = audio.eqCurve, n = pts.length
        if (!n) return 0
        const t = Math.max(0, Math.min(n - 1, Math.log(f / 20) / Math.log(1000) * (n - 1)))
        const i = Math.floor(t), fr = t - i
        return i + 1 < n ? pts[i] * (1 - fr) + pts[i + 1] * fr : pts[i]
    }
    readonly property real padY: 22
    function fx(f) { return Math.log(f / 20) / Math.log(1000) * width }
    function gy(db) { return height / 2 - db / range * (height / 2 - padY) }
    function fmtF(f) { return f >= 1000 ? (f / 1000) + "k" : "" + f }
    function rgba(c, a) { return "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + "," + Math.round(c.b * 255) + "," + a + ")" }

    Canvas {
        id: grid
        anchors.fill: parent
        onWidthChanged: requestPaint(); onHeightChanged: requestPaint()
        Connections { target: Theme; function onSeedChanged() { grid.requestPaint() } function onDarkChanged() { grid.requestPaint() } }
        onPaint: {
            const ctx = getContext("2d"); ctx.reset()
            ctx.lineWidth = 1
            const stepDb = root.range > 21 ? 12 : 6
            for (let db = -Math.floor((root.range - 1) / stepDb) * stepDb; db < root.range - 1; db += stepDb) {
                const y = Math.round(root.gy(db)) + 0.5
                ctx.strokeStyle = root.rgba(Theme.outlineVariant, db === 0 ? 1 : 0.55)
                ctx.setLineDash(db === 0 ? [] : [2, 6])
                ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke()
                ctx.fillStyle = root.rgba(Theme.inkVariant, 0.7)
                ctx.font = "11px '" + Theme.font + "'"
                ctx.fillText((db > 0 ? "+" : "") + db, 6, y - 4)
            }
            ctx.setLineDash([2, 6])
            for (const f of [50, 100, 200, 500, 1000, 2000, 5000, 10000]) {
                const x = Math.round(root.fx(f)) + 0.5
                ctx.strokeStyle = root.rgba(Theme.outlineVariant, 0.35)
                ctx.beginPath(); ctx.moveTo(x, root.padY); ctx.lineTo(x, height - root.padY); ctx.stroke()
            }
        }
    }

    Spectrum {
        x: root.fx(28); width: root.fx(18000) - x
        height: parent.height
        showBefore: false
        lineWidth: 1.5
        opacity: 0.32
    }

    Canvas {
        id: curve
        anchors.fill: parent
        property var pts: audio.eqCurve
        onPtsChanged: requestPaint()
        onWidthChanged: requestPaint()
        Connections { target: Theme; function onSeedChanged() { curve.requestPaint() } }
        onPaint: {
            const ctx = getContext("2d"); ctx.reset()
            const n = pts.length; if (!n) return
            const y0 = root.gy(0)
            ctx.beginPath(); ctx.moveTo(0, y0)
            for (let i = 0; i < n; i++) ctx.lineTo(i / (n - 1) * width, root.gy(pts[i]))
            ctx.lineTo(width, y0); ctx.closePath()
            const g = ctx.createLinearGradient(0, root.padY, 0, height - root.padY)
            g.addColorStop(0, root.rgba(Theme.primary, 0.35)); g.addColorStop(0.5, root.rgba(Theme.primary, 0.04))
            g.addColorStop(1, root.rgba(Theme.tertiary, 0.35))
            ctx.fillStyle = g; ctx.fill()
            ctx.beginPath()
            for (let i = 0; i < n; i++) { const x = i / (n - 1) * width, y = root.gy(pts[i]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) }
            ctx.lineWidth = 4; ctx.lineJoin = "round"; ctx.lineCap = "round"
            const lg = ctx.createLinearGradient(0, 0, width, 0)
            lg.addColorStop(0, root.rgba(Theme.primary, 1)); lg.addColorStop(1, root.rgba(Theme.tertiary, 1))
            ctx.strokeStyle = lg; ctx.stroke()
        }
    }

    Repeater {
        model: root.freqs.length
        delegate: Item {
            id: h
            required property int index
            readonly property string key: "eq" + index
            readonly property real gain: audio.params[key] || 0
            readonly property bool active: ma.pressed || ma.containsMouse || activeFocus
            activeFocusOnTab: true
            readonly property real value: gain
            readonly property real minimumValue: -15
            readonly property real maximumValue: 15
            Accessible.role: Accessible.Slider
            Accessible.name: root.fmtF(root.freqs[index]) + " Hz equalizer"
            Accessible.description: gain.toFixed(1) + " dB"
            Accessible.onIncreaseAction: audio.setParam(key, Math.min(15, gain + 0.5))
            Accessible.onDecreaseAction: audio.setParam(key, Math.max(-15, gain - 0.5))
            Keys.onPressed: (event) => {
                if (event.key === Qt.Key_Up || event.key === Qt.Key_Right) audio.setParam(key, Math.min(15, gain + 0.5))
                else if (event.key === Qt.Key_Down || event.key === Qt.Key_Left) audio.setParam(key, Math.max(-15, gain - 0.5))
                else if (event.key === Qt.Key_Home) audio.setParam(key, 0)
                else return
                event.accepted = true
            }
            FocusRing { radius: 25 }
            readonly property real curveDb: root.curveAt(root.freqs[index])
            width: 44; height: 44
            x: root.fx(root.freqs[index]) - width / 2
            y: root.gy(gain) - height / 2
            Behavior on y { enabled: !ma.pressed; NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack } }

            // stem to the summed curve: how much the neighbouring bands add on top of this one
            Rectangle {
                readonly property real dy: root.gy(h.curveDb) - root.gy(h.gain)
                visible: Math.abs(h.curveDb - h.gain) > 1.5
                anchors.horizontalCenter: parent.horizontalCenter
                width: 2; radius: 1
                y: parent.height / 2 + Math.min(0, dy)
                height: Math.abs(dy)
                color: Theme.primary
                opacity: 0.35
            }
            MorphShape {
                anchors.centerIn: parent
                width: ma.pressed ? 40 : 26; height: width
                Behavior on width { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack } }
                shape: ma.pressed ? "cookie9" : "circle"
                spinning: ma.pressed
                spinDuration: 4000
                color: Theme.primary; color2: Theme.tertiary
                strokeWidth: 3; strokeColor: Theme.surface
            }
            Rectangle { anchors.centerIn: parent; width: 8; height: 8; radius: 4; color: Theme.inkPrimary }
            Rectangle {
                visible: opacity > 0
                opacity: h.active ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                anchors.horizontalCenter: parent.horizontalCenter
                y: h.gain >= 0 ? -height - 2 : parent.height + 2
                width: tip.implicitWidth + 20; height: 30; radius: 15
                color: Theme.inverseSurface
                Text { id: tip; anchors.centerIn: parent
                       text: (h.gain > 0 ? "+" : "") + h.gain.toFixed(1) + " dB · " + root.fmtF(root.freqs[h.index]) + "Hz"
                       color: Theme.inverseOnSurface; font.family: Theme.font; font.pixelSize: 12; font.weight: Font.DemiBold }
            }
            MouseArea {
                id: ma
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.SizeVerCursor
                preventStealing: true
                property real y0; property real g0
                onPressed: (e) => { y0 = mapToItem(root, e.x, e.y).y; g0 = h.gain; root.dragging++ }
                onReleased: root.dragging = Math.max(0, root.dragging - 1)
                onCanceled: root.dragging = Math.max(0, root.dragging - 1)
                onPositionChanged: (e) => {
                    if (!pressed) return
                    const dy = mapToItem(root, e.x, e.y).y - y0
                    let g = g0 - dy / (root.height / 2 - root.padY) * root.range
                    g = Math.max(-15, Math.min(15, Math.round(g * 10) / 10))
                    audio.setParam(h.key, g)
                }
                onDoubleClicked: audio.setParam(h.key, 0)
                onWheel: (w) => audio.setParam(h.key, Math.max(-15, Math.min(15, h.gain + (w.angleDelta.y > 0 ? 0.5 : -0.5))))
            }
        }
    }
}
