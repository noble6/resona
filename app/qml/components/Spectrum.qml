import QtQuick

// Live analyzer: "before" as a thin ghost line, "after" as a glowing filled curve.
Canvas {
    id: c
    property var before: audio.spectrumIn
    property var after: audio.spectrumOut
    property bool showBefore: true
    property real lineWidth: 3
    onAfterChanged: requestPaint()
    onWidthChanged: requestPaint()
    Connections { target: Theme; function onSeedChanged() { c.requestPaint() } function onDarkChanged() { c.requestPaint() } }

    function rgba(col, a) { return "rgba(" + Math.round(col.r * 255) + "," + Math.round(col.g * 255) + "," + Math.round(col.b * 255) + "," + a + ")" }
    function trace(ctx, vals, w, h) {
        const n = vals.length
        if (!n) return
        const px = i => i / (n - 1) * w, py = v => h - 6 - v * (h - 12)
        ctx.moveTo(0, py(vals[0]))
        for (let i = 1; i < n - 1; i++) {
            const xc = (px(i) + px(i + 1)) / 2, yc = (py(vals[i]) + py(vals[i + 1])) / 2
            ctx.quadraticCurveTo(px(i), py(vals[i]), xc, yc)
        }
        ctx.lineTo(w, py(vals[n - 1]))
    }
    onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        const w = width, h = height
        if (!after || !after.length) return
        // after: filled
        ctx.beginPath()
        trace(ctx, after, w, h)
        ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath()
        const g = ctx.createLinearGradient(0, 0, 0, h)
        g.addColorStop(0, rgba(Theme.primary, 0.55))
        g.addColorStop(0.6, rgba(Theme.tertiary, 0.18))
        g.addColorStop(1, rgba(Theme.tertiary, 0))
        ctx.fillStyle = g
        ctx.fill()
        ctx.beginPath()
        trace(ctx, after, w, h)
        ctx.lineWidth = lineWidth
        ctx.lineCap = "round"; ctx.lineJoin = "round"
        const lg = ctx.createLinearGradient(0, 0, w, 0)
        lg.addColorStop(0, rgba(Theme.primary, 1))
        lg.addColorStop(1, rgba(Theme.tertiary, 1))
        ctx.strokeStyle = lg
        ctx.stroke()
        if (showBefore && before && before.length) {
            ctx.beginPath()
            trace(ctx, before, w, h)
            ctx.lineWidth = 1.5
            ctx.setLineDash([3, 4])
            ctx.strokeStyle = rgba(Theme.inkVariant, 0.55)
            ctx.stroke()
        }
    }
}
