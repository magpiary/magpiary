// The first-run window: a web view showing packaging/app/installer, the page designed with the owner, so it looks exactly like the hub.
// The page and the hub's styles are served from inside the app over a private scheme; nothing leaves the Mac and no server is needed.
import AppKit
import WebKit

/// Answers magpiary://app/... from the app itself: /static/ from Magpiary's own files (the hub's CSS, fonts, art), /panel/ from the menu-bar page, the rest from the installer page.
final class PageFiles: NSObject, WKURLSchemeHandler {
    let page = Bundle.main.resourceURL!.appendingPathComponent("installer")
    let panel = Bundle.main.resourceURL!.appendingPathComponent("panel")
    let hub = Bundle.main.resourceURL!.appendingPathComponent("python/lib/python3.12/site-packages/magpiary/static")
    let types = ["html": "text/html", "css": "text/css", "js": "text/javascript", "svg": "image/svg+xml", "webp": "image/webp", "woff2": "font/woff2"]

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        let path = task.request.url?.path ?? "/"
        let root = path.hasPrefix("/static/") ? hub : path.hasPrefix("/panel/") ? panel : page
        let name = root == page ? String(path.dropFirst()) : String(path.drop(while: { $0 == "/" }).drop(while: { $0 != "/" }).dropFirst())
        let file = root.appendingPathComponent(name).standardizedFileURL
        guard file.path.hasPrefix(root.standardizedFileURL.path + "/"), let data = try? Data(contentsOf: file) else {
            task.didFailWithError(URLError(.fileDoesNotExist))
            return
        }
        let headers = ["Content-Type": types[file.pathExtension] ?? "application/octet-stream"]
        task.didReceive(HTTPURLResponse(url: task.request.url!, statusCode: 200, httpVersion: nil, headerFields: headers)!)
        task.didReceive(data)
        task.didFinish()
    }
    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}
}

/// The page has no web-browser menu.
final class PageView: WKWebView {
    override func willOpenMenu(_ menu: NSMenu, with event: NSEvent) { menu.removeAllItems() }
}

/// Lets the window be dragged by its top strip (a web view would otherwise swallow the drag).
final class DragStrip: NSView {
    override var mouseDownCanMoveWindow: Bool { true }
}

final class InstallerWindow: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    let window: NSWindow
    let web: PageView
    private var ready = false
    private var waiting: [String] = []
    private let onAction: (String) -> Void

    init(onAction: @escaping (String) -> Void) {
        self.onAction = onAction
        let size = NSRect(x: 0, y: 0, width: 1100, height: 700)
        window = NSWindow(contentRect: size, styleMask: [.titled, .closable, .miniaturizable, .fullSizeContentView], backing: .buffered, defer: false)
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.appearance = NSAppearance(named: .darkAqua)
        window.backgroundColor = NSColor(red: 0.043, green: 0.043, blue: 0.055, alpha: 1)
        window.isReleasedWhenClosed = false
        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(PageFiles(), forURLScheme: "magpiary")
        web = PageView(frame: size, configuration: config)
        web.autoresizingMask = [.width, .height]
        web.setValue(false, forKey: "drawsBackground")
        super.init()
        config.userContentController.add(self, name: "magpiary")
        web.navigationDelegate = self
        let holder = NSView(frame: size)
        holder.addSubview(web)
        let strip = DragStrip(frame: NSRect(x: 0, y: size.height - 74, width: size.width, height: 74))
        strip.autoresizingMask = [.width, .minYMargin]
        holder.addSubview(strip)
        window.contentView = holder
        window.center()
        web.load(URLRequest(url: URL(string: "magpiary://app/index.html")!))
    }

    func show() {
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    /// Hands one installer event to the page, holding it until the page has loaded.
    func send(_ event: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: event), let json = String(data: data, encoding: .utf8) else { return }
        if ready { web.evaluateJavaScript("window.magpiaryEvent(\(json))") } else { waiting.append(json) }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        ready = true
        waiting.forEach { web.evaluateJavaScript("window.magpiaryEvent(\($0))") }
        waiting = []
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        if let action = message.body as? String { onAction(action) }
    }
}
