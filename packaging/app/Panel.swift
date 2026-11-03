// The menu-bar panel: a small floating window showing packaging/app/panel, the page designed with the owner.
import AppKit
import WebKit

/// A borderless window can't take typing unless it says so, and the search box needs typing.
final class KeyPanel: NSPanel {
    override var canBecomeKey: Bool { true }
}

final class MenuPanel: NSObject, WKScriptMessageHandler, WKNavigationDelegate, NSWindowDelegate {
    let window: KeyPanel
    let web: PageView
    private var ready = false
    private var state = "null"
    private let onMessage: ([String: Any]) -> Void
    static let width: CGFloat = 340

    init(onMessage: @escaping ([String: Any]) -> Void) {
        self.onMessage = onMessage
        let size = NSRect(x: 0, y: 0, width: MenuPanel.width, height: 400)
        window = KeyPanel(contentRect: size, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.level = .popUpMenu
        window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: .darkAqua)
        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(PageFiles(), forURLScheme: "magpiary")
        web = PageView(frame: size, configuration: config)
        web.autoresizingMask = [.width, .height]
        web.setValue(false, forKey: "drawsBackground")
        super.init()
        config.userContentController.add(self, name: "panel")
        web.navigationDelegate = self
        window.contentView = web
        window.delegate = self
        web.load(URLRequest(url: URL(string: "magpiary://app/panel/index.html")!))
    }

    var isShown: Bool { window.isVisible }

    /// Opens under the menu-bar icon, kept on screen.
    func show(under button: NSStatusBarButton) {
        guard let bar = button.window else { return }
        let icon = bar.convertToScreen(button.convert(button.bounds, to: nil))
        place(iconMaxX: icon.maxX, top: icon.minY - 6, screen: bar.screen)
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    func close() { window.orderOut(nil) }

    private func place(iconMaxX: CGFloat, top: CGFloat, screen: NSScreen?) {
        var x = iconMaxX - MenuPanel.width
        if let limit = screen?.visibleFrame { x = min(max(x, limit.minX + 8), limit.maxX - MenuPanel.width - 8) }
        window.setFrameTopLeftPoint(NSPoint(x: x, y: top))
    }

    func windowDidResignKey(_ notification: Notification) { close() }

    /// Hands the page the latest state (kept until the page has loaded).
    func update(_ newState: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: newState), let json = String(data: data, encoding: .utf8) else { return }
        state = json
        if ready { web.evaluateJavaScript("window.magpiaryPanel(\(json))") }
    }

    func saved(_ result: String) { web.evaluateJavaScript("window.magpiarySaved('\(result)')") }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        ready = true
        if state != "null" { web.evaluateJavaScript("window.magpiaryPanel(\(state))") }
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        if let height = body["height"] as? Double, height > 0 {
            let top = window.frame.maxY   // grow downwards from the menu bar
            window.setContentSize(NSSize(width: MenuPanel.width, height: height))
            window.setFrameTopLeftPoint(NSPoint(x: window.frame.minX, y: top))
            window.invalidateShadow()
        } else {
            onMessage(body)
        }
    }
}
