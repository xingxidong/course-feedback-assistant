// Print on-screen WeChat windows as "x y w h" lines, front-to-back.
//
// Why this exists: System Events reports a window frame even when that window is
// occluded, on another Space, or behind other apps. `screencapture -R` captures
// whatever pixels are drawn at those coordinates, so OCR would silently read a
// different application. The window server list is the ground truth for what the
// user is actually seeing.
import Cocoa

let opts = CGWindowListOption(arrayLiteral: .excludeDesktopElements)
let list = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as! [[String: Any]]
for w in list {
    let owner = w[kCGWindowOwnerName as String] as? String ?? "?"
    guard owner == "WeChat" || owner == "微信" else { continue }
    let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
    let x = b["X"] as? Double ?? -1, y = b["Y"] as? Double ?? -1
    let ww = b["Width"] as? Double ?? -1, hh = b["Height"] as? Double ?? -1
    let layer = w[kCGWindowLayer as String] as? Int ?? -1
    let onscreen = w[kCGWindowIsOnscreen as String] as? Bool ?? false
    let alpha = w[kCGWindowAlpha as String] as? Double ?? -1
    // Exclude tooltips/panels (layer != 0) and fully transparent or tiny helper windows.
    if ww >= 400 && hh >= 300 && layer == 0 && onscreen && alpha > 0.05 {
        print(String(format: "%d %d %d %d", Int(x), Int(y), Int(ww), Int(hh)))
    }
}
