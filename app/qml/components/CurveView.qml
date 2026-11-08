import QtQuick

// Small frequency-response plot (20 Hz–20 kHz, ±range dB) for correction curves.
Canvas {
    id: c
    property var points: []
    property real range: 12
    onPointsChanged: requestPaint()
    onWidthChanged: requestPaint()
    Connections { target: Theme; function onSeedChanged() { c.requestPaint() } function onDarkChanged() { c.requestPaint() } }
    function rgba(col, a) { return "rgba(" + Math.round(col.r * 255) + "," + Math.round(col.g * 255) + "," + Math.round(col.b * 255) + "," + a + ")" }
    function gy(db) { return height / 2 - db / range * (height / 2 - 8) }
    onPaint: {
        const ctx = getContext("2d"); ctx.reset()
        ctx.lineWidth = 1
        for (const db of [-range / 2, 0, range / 2]) {
            ctx.strokeStyle = rgba(Theme.outlineVariant, db === 0 ? 1 : 0.5)
            ctx.setLineDash(db === 0 ? [] : [2, 5])
            ctx.beginPath(); ctx.moveTo(0, gy(db)); ctx.lineTo(width, gy(db)); ctx.stroke()
        }
        ctx.setLineDash([])
        for (const f of [100, 1000, 10000]) {
            const x = Math.log(f / 20) / Math.log(1000) * width
            ctx.strokeStyle = rgba(Theme.outlineVariant, 0.4)
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke()
            ctx.fillStyle = rgba(Theme.inkVariant, 0.8); ctx.font = "11px '" + Theme.font + "'"
            ctx.fillText(f >= 1000 ? (f / 1000) + "k" : f, x + 4, height - 4)
        }
        const n = points.length; if (!n) return
        ctx.beginPath(); ctx.moveTo(0, gy(0))
        for (let i = 0; i < n; i++) ctx.lineTo(i / (n - 1) * width, gy(Math.max(-range, Math.min(range, points[i]))))
        ctx.lineTo(width, gy(0)); ctx.closePath()
        ctx.fillStyle = rgba(Theme.tertiary, 0.18); ctx.fill()
        ctx.beginPath()
        for (let i = 0; i < n; i++) { const x = i / (n - 1) * width, y = gy(Math.max(-range, Math.min(range, points[i]))); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) }
        ctx.lineWidth = 3; ctx.lineJoin = "round"; ctx.strokeStyle = rgba(Theme.tertiary, 1); ctx.stroke()
    }
}
