// Magpiary.app: a native shell around the bundled Python.
// It shows the first-run downloads in a window (a web view of packaging/app/installer), keeps the background service running, and lives in the menu bar (a web view of packaging/app/panel).
// Everything real (hub, pipeline, downloads) is the bundled `magpiary` program; this only starts and shows it.
//
// Environment (tests and screenshots): MAGPIARY_PORT, MAGPIARY_HOME, MAGPIARY_CONFIG pass through to the program;
// MAGPIARY_NO_SERVICE=1 runs the receiver as a child of this app instead of installing the launchd service;
// MAGPIARY_DEMO=ok|offline|disk plays a pretend install; MAGPIARY_SNAPSHOT_DIR saves PNGs of each state.

import AppKit

let env = ProcessInfo.processInfo.environment
// One port per Mac account (the first account 8765, the next 8766, ...), so two accounts never meet in one hub or one library.
let port = Int(env["MAGPIARY_PORT"] ?? "") ?? (8765 + (Int(getuid()) - 501 + 20) % 20)
let noService = env["MAGPIARY_NO_SERVICE"] == "1"
let demo = env["MAGPIARY_DEMO"] ?? ""
let snapshotDir = env["MAGPIARY_SNAPSHOT_DIR"] ?? ""
let bundlePython = Bundle.main.resourceURL!.appendingPathComponent("python/bin")
let program = bundlePython.appendingPathComponent("magpiary")

enum Colors {
    static let gold = NSColor(red: 1, green: 0.82, blue: 0.48, alpha: 1)
    static let pink = NSColor(red: 1, green: 0.31, blue: 0.64, alpha: 1)
    static let bad = NSColor(red: 1, green: 0.54, blue: 0.56, alpha: 1)
}

final class Shell: NSObject, NSApplicationDelegate {
    let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let dot = NSView(frame: NSRect(x: 0, y: 0, width: 7, height: 7))
    lazy var panel: MenuPanel = MenuPanel { [unowned self] message in self.panelMessage(message) }
    var settingUpFraction: Double?   // set while the first-run downloads run
    var saveToken = ""               // the hub's form token, needed to save a link
    lazy var installer: InstallerWindow = InstallerWindow { [unowned self] action in
        switch action {
        case "retry": self.start()
        case "continue": self.installer.window.close(); self.open("/")
        case "proceed": self.placeChecked = true; self.start()
        default: self.quit()
        }
    }
    var settingUp = false        // the window has something to show (there were downloads to do)
    var child: Process?          // the receiver, when MAGPIARY_NO_SERVICE=1
    var working = false
    var serviceError = ""        // what `service install` printed when it failed, so the window can say why
    var startedOnce = false      // the first start() of this launch decides whether to open the library by itself
    var placeChecked = false     // the user chose to carry on from a folder the service can't run from

    /// True when this copy sits in /Applications or ~/Applications. Anywhere else (Desktop, Downloads, the mounted disk image)
    /// macOS may refuse to run the background service, so the window says so before anything is downloaded.
    var inApplications: Bool {
        let path = Bundle.main.bundleURL.resolvingSymlinksInPath().path
        let mine = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications").path
        return path.hasPrefix("/Applications/") || path.hasPrefix(mine + "/")
    }

    // ---- launch -----------------------------------------------------------------------------

    func applicationDidFinishLaunching(_ note: Notification) {
        if let path = Bundle.main.path(forResource: "symbol-black", ofType: "png"), let icon = NSImage(contentsOfFile: path) {
            icon.isTemplate = true
            icon.size = NSSize(width: 18, height: 18)
            statusItem.button?.image = icon
        } else {
            statusItem.button?.image = NSImage(systemSymbolName: "books.vertical", accessibilityDescription: "Magpiary")
        }
        statusItem.button?.target = self
        statusItem.button?.action = #selector(togglePanel(_:))
        dot.wantsLayer = true
        dot.layer?.cornerRadius = 3.5
        dot.isHidden = true
        statusItem.button?.addSubview(dot)
        _ = panel
        // The first open can take minutes before any program answers (macOS checks every file of a new app), so the
        // window comes first, from this native code alone; the downloads follow when the bundled program has started.
        if !UserDefaults.standard.bool(forKey: "setupComplete") {
            settingUp = true
            installer.show()
        }
        start()
        Timer.scheduledTimer(withTimeInterval: 4, repeats: true) { _ in self.refresh() }
    }

    // magpiary://uninstall is the button in Settings: the hub can't remove the app it runs from, so it asks the app. It only opens the question below.
    func application(_ application: NSApplication, open urls: [URL]) {
        if urls.contains(where: { $0.host == "uninstall" }) { uninstall() }
        if urls.contains(where: { $0.host == "open" }) { open("/") }   // the "Start Magpiary" button of the installed web app's offline page
    }

    // Opening the app again (Dock, Spotlight): the installer while setup is not finished (and it starts the setup if nothing is
    // running), the library once it is.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !setupDone || !canConnect() { showInstaller() } else { open("/") }
        return true
    }

    @objc func togglePanel(_ sender: Any?) {
        guard let button = statusItem.button else { return }
        if panel.isShown { panel.close() } else {
            refresh()
            panel.show(under: button)
        }
    }

    // ---- start-up: finish the downloads, then make sure the receiver runs ---------------------

    func start() {
        if working { return }
        if !noService && demo.isEmpty && snapshotDir.isEmpty && !inApplications && !placeChecked { settingUp = true; installer.show(); installer.send(["event": "misplaced"]); return }
        working = true
        DispatchQueue.global().async {
            let installed = demo.isEmpty ? self.runDownloads() : self.runDemo()
            guard installed else { self.working = false; return }
            UserDefaults.standard.set(true, forKey: "setupComplete")
            DispatchQueue.main.async { if self.settingUp { self.installer.send(["event": "starting"]) } }
            self.startService()
            let up = self.waitForHub(seconds: 40)
            DispatchQueue.main.async {
                let first = !self.startedOnce
                self.startedOnce = true
                if !up && !self.settingUp { self.settingUp = true; self.installer.show() }   // a relaunch that can't start must not stay silent
                if self.settingUp { self.installer.send(up ? ["event": "ready"] : ["event": "start_failed", "reason": self.friendlyReason()]) }
                // A relaunch after setup shows no window, so the library opens by itself once the hub is up.
                if up && first && !self.settingUp && snapshotDir.isEmpty && demo.isEmpty { self.open("/") }
                self.working = false
                self.setProgress(nil)
                self.refresh()
                self.snapshotLater("done", delay: 2.5)
                if !snapshotDir.isEmpty && up {   // screenshots only: show the menu-bar panel once the hub is up
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3) { self.togglePanel(nil) }
                    self.snapshotLater("panel", delay: 5, panel: true)
                }
            }
        }
    }

    func startService(force: Bool = false) {
        if noService {
            let p = Process()
            p.executableURL = program
            p.arguments = ["serve", "--port", String(port)]
            p.environment = env
            try? p.run()
            child = p
        } else {
            // A new version dropped over the old one must replace the service still running the old code.
            let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
            let seen = UserDefaults.standard.string(forKey: "serviceVersion")
            if force || !serviceIsCurrent() || seen != version {
                serviceError = ""
                if run(["service", "install", "--port", String(port)], capture: true) == 0 { UserDefaults.standard.set(version, forKey: "serviceVersion") }
            }
        }
    }

    func waitForHub(seconds: Int) -> Bool {
        for _ in 0..<(seconds * 2) { if canConnect() { return true }; Thread.sleep(forTimeInterval: 0.5) }
        return false
    }

    /// Runs `magpiary downloads install --json`, feeding every event to the window. Returns true when everything is in place.
    func runDownloads() -> Bool {
        let p = Process()
        p.executableURL = program
        p.arguments = ["downloads", "install", "--json"]
        p.environment = env
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch {
            DispatchQueue.main.async {
                self.settingUp = true
                self.installer.show()
                self.installer.send(["event": "step_error", "kind": "server", "message": "Magpiary couldn’t start its installer."])
            }
            return false
        }
        var ok = false
        readLines(pipe) { line in   // each event goes to the window as it arrives, so progress is live
            guard let data = line.data(using: .utf8), let e = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let kind = e["event"] as? String else { return }
            DispatchQueue.main.async { self.handle(e, kind) }
            if kind == "finished" { ok = (e["ok"] as? Bool) ?? false }
        }
        p.waitUntilExit()
        return ok
    }

    func handle(_ e: [String: Any], _ kind: String) {
        if (kind == "plan" && (e["steps"] as? [Any])?.isEmpty == false) || kind == "precheck" || kind == "step_error" {
            settingUp = true
            installer.show()
        }
        if settingUp { installer.send(e) }
        if kind == "progress", let d = e["overall_done"] as? Double, let t = e["overall_total"] as? Double, t > 0 { setProgress(d / t) }
    }

    func setProgress(_ fraction: Double?) {
        settingUpFraction = fraction
        refresh()
    }

    /// Hands every line the program prints to `each`, as soon as it is complete, until the program closes its output.
    func readLines(_ pipe: Pipe, _ each: (String) -> Void) {
        var buffer = Data()
        while true {
            let chunk = pipe.fileHandleForReading.availableData
            if chunk.isEmpty { break }
            buffer.append(chunk)
            while let range = buffer.firstRange(of: Data([10])) {
                if let line = String(data: buffer.subdata(in: buffer.startIndex..<range.lowerBound), encoding: .utf8) { each(line) }
                buffer.removeSubrange(buffer.startIndex...range.lowerBound)
            }
        }
    }

    /// True if the launchd agent already starts this copy of the program through this app's launcher (Contents/MacOS/magpiary-hub,
    /// so macOS prompts name Magpiary). Moving the app, or an agent from before the launcher, needs the agent rewritten.
    func serviceIsCurrent() -> Bool {
        let plist = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents/org.magpiary.receiver.plist")
        guard let data = try? Data(contentsOf: plist),
              let dict = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              let args = dict["ProgramArguments"] as? [String], args.count >= 2 else { return false }
        let launcher = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/magpiary-hub").path
        return args[0] == launcher && args[1] == program.path
    }

    /// Runs the bundled program. With `capture`, what it prints on stderr is kept in `serviceError` (the reason a step failed).
    @discardableResult
    func run(_ args: [String], capture: Bool = false) -> Int32 {
        let p = Process()
        p.executableURL = program
        p.arguments = args
        p.environment = env
        p.standardOutput = FileHandle.nullDevice
        let errors = Pipe()
        p.standardError = capture ? errors : FileHandle.nullDevice
        do { try p.run() } catch { if capture { serviceError = "\(error.localizedDescription)" }; return -1 }
        var text = Data()
        if capture { text = errors.fileHandleForReading.readDataToEndOfFile() }
        p.waitUntilExit()
        if capture { serviceError = String(data: text, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "" }
        return p.terminationStatus
    }

    /// The plain-language reason Magpiary didn't start. A folder macOS keeps background services out of, or any copy outside
    /// Applications, gets the move-it advice; anything else shows what the service said.
    func friendlyReason() -> String {
        if !inApplications || serviceError.contains("macOS does not let background services") {
            return "Magpiary can’t keep running in the background from here. Move Magpiary to your Applications folder, then open it again."
        }
        if !serviceError.isEmpty {
            return "Everything downloaded fine, but Magpiary didn’t start. It said: \(serviceError.split(separator: "\n").first.map(String.init) ?? serviceError)"
        }
        return ""
    }

    // ---- status for the menu-bar panel ------------------------------------------------------

    var hub: String { "http://127.0.0.1:\(port)" }

    func refresh() {
        if let fraction = settingUpFraction {
            show(["kind": "setup", "percent": Int(fraction * 100), "latest": []], dot: Colors.gold)
            return
        }
        DispatchQueue.global().async {
            guard self.canConnect() else { DispatchQueue.main.async { self.showHub(nil) }; return }   // not ours: show nothing from it
            var request = URLRequest(url: URL(string: "\(self.hub)/panel.json")!)
            request.timeoutInterval = 3
            URLSession.shared.dataTask(with: request) { data, _, _ in
                let d = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                DispatchQueue.main.async { self.showHub(d) }
            }.resume()
        }
    }

    func showHub(_ d: [String: Any]?) {
        guard settingUpFraction == nil else { return }
        guard let d = d else {
            show(["kind": working ? "setup" : "stopped", "percent": 0, "latest": []], dot: working ? Colors.gold : Colors.bad)
            return
        }
        saveToken = d["csrf"] as? String ?? ""
        if d["locked"] as? Bool == true { show(["kind": "locked", "latest": []], dot: nil); return }
        var state = d
        state["kind"] = "running"
        state["hub"] = hub
        state["csrf"] = nil
        let need = d["need"] as? Int ?? 0, waiting = d["waiting"] as? Int ?? 0
        show(state, dot: need > 0 ? Colors.pink : waiting > 0 ? Colors.gold : nil)
    }

    func show(_ state: [String: Any], dot colour: NSColor?) {
        panel.update(state)
        dot.isHidden = colour == nil
        dot.layer?.backgroundColor = colour?.cgColor
        if let button = statusItem.button { dot.frame.origin = NSPoint(x: button.bounds.maxX - 9, y: button.isFlipped ? 3 : button.bounds.maxY - 10) }
    }

    // ---- what the panel asks for --------------------------------------------------------------

    func panelMessage(_ message: [String: Any]) {
        if let words = message["search"] as? String {
            var query = URLComponents()
            query.queryItems = [URLQueryItem(name: "q", value: words)]
            panel.close()
            open("/\(query.url?.absoluteString ?? "")")
            return
        }
        guard let action = message["action"] as? String else { return }
        switch action {
        case "save": saveCopiedLink()
        case "close": panel.close()
        case "quit": quit()
        case "installer": panel.close(); installer.show()
        case "start":
            DispatchQueue.global().async {
                self.startService(force: true)
                _ = self.waitForHub(seconds: 20)
                DispatchQueue.main.async { self.refresh() }
            }
        default:
            if action.hasPrefix("open:") { panel.close(); open(String(action.dropFirst(5))) }
        }
    }

    /// Reads the clipboard only now, when asked, and only keeps what looks like a web link.
    func saveCopiedLink() {
        let copied = (NSPasteboard.general.string(forType: .string) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let scheme = URL(string: copied)?.scheme?.lowercased()
        guard scheme == "http" || scheme == "https", !copied.contains(where: { $0.isWhitespace }) else { panel.saved("none"); return }
        var form = URLComponents()
        form.queryItems = [URLQueryItem(name: "csrf", value: saveToken), URLQueryItem(name: "url", value: copied)]
        var request = URLRequest(url: URL(string: "\(hub)/hub/panel/save")!)
        request.httpMethod = "POST"
        request.timeoutInterval = 10
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        // A + or & in the link must survive form encoding (URLComponents leaves + alone).
        request.httpBody = form.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B").data(using: .utf8)
        URLSession.shared.dataTask(with: request) { data, response, _ in
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            let d = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let result = code == 423 ? "locked" : (d?["status"] as? String ?? "failed")
            DispatchQueue.main.async { self.panel.saved(result); self.refresh() }
        }.resume()
    }

    /// True only when a Magpiary hub answers on this account's port and says it belongs to this Mac account. Another account's hub
    /// (or an older one that does not say whose it is) does not count: its library must never be shown to this user.
    func canConnect() -> Bool {
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/ping") else { return false }
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.5
        request.cachePolicy = .reloadIgnoringLocalCacheData
        var mine = false
        let done = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: request) { data, response, _ in
            if (response as? HTTPURLResponse)?.statusCode == 200,
               let d = data.flatMap({ try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }),
               (d["uid"] as? Int) == Int(getuid()) { mine = true }
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + 2)
        return mine
    }

    // ---- actions -----------------------------------------------------------------------------

    /// The library opens in the browser only when setup has finished and this app's hub answers. Until then every way in (the Dock,
    /// the menu bar, a link from the panel) brings back the installer window instead, and starts the setup if it is not running.
    var setupDone: Bool { UserDefaults.standard.bool(forKey: "setupComplete") }

    func showInstaller() {
        settingUp = true
        installer.show()
        start()   // does nothing while the downloads are already running
    }

    func open(_ path: String) {
        guard setupDone, canConnect() else { showInstaller(); return }
        if path == "/", let installed = installedWebApp() {   // the library itself opens in the installed web app window
            NSWorkspace.shared.openApplication(at: installed, configuration: NSWorkspace.OpenConfiguration()) { _, _ in }
            return
        }
        NSWorkspace.shared.open(URL(string: "http://localhost:\(port)\(path)")!)
    }

    /// The Chrome, Edge or Brave "install as app" copy of this hub, if the user made one (Settings > Appearance > Install as app).
    /// Chromium keeps them in ~/Applications/<Browser> Apps.localized/Magpiary.app and records the address in the shim's Info.plist
    /// (CrAppModeShortcutURL), so only a copy of THIS account's hub counts. Anything unexpected: nil, and the browser opens as before.
    /// Only the first account's port can be installed (Settings says so).
    func installedWebApp() -> URL? {
        let home = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications")
        guard let folders = try? FileManager.default.contentsOfDirectory(atPath: home.path) else { return nil }
        for folder in folders where folder.hasSuffix("Apps.localized") {
            let app = home.appendingPathComponent(folder).appendingPathComponent("Magpiary.app")
            guard let info = NSDictionary(contentsOf: app.appendingPathComponent("Contents/Info.plist")),
                  let address = info["CrAppModeShortcutURL"] as? String,
                  let url = URL(string: address), url.host == "localhost", url.port == port else { continue }
            return app
        }
        return nil
    }

    func quit() {
        child?.terminate()
        NSApp.terminate(nil)
    }

    func uninstall() {
        panel.close()
        let alert = NSAlert()
        alert.messageText = "Uninstall Magpiary?"
        alert.informativeText = "This stops the background service and removes the downloaded tools and models. Your library stays unless you choose to delete it."
        alert.addButton(withTitle: "Uninstall, keep my library")
        alert.addButton(withTitle: "Uninstall and delete my library")
        alert.addButton(withTitle: "Cancel")
        let answer = alert.runModal()
        if answer == .alertThirdButtonReturn { return }
        if answer == .alertSecondButtonReturn {
            let sure = NSAlert()
            sure.messageText = "Delete your whole library?"
            sure.informativeText = "Every saved post, note and setting is deleted for good. This can’t be undone."
            sure.alertStyle = .critical
            sure.addButton(withTitle: "Delete everything")
            sure.addButton(withTitle: "Cancel")
            if sure.runModal() != .alertFirstButtonReturn { return }
        }
        child?.terminate()
        var args = ["uninstall", "--yes"]
        if answer == .alertSecondButtonReturn { args.append("--delete-library") }
        DispatchQueue.global().async {
            self.run(args)
            DispatchQueue.main.async {
                NSWorkspace.shared.recycle([Bundle.main.bundleURL]) { _, _ in NSApp.terminate(nil) }
            }
        }
    }

    // ---- demo and screenshots (never used by a real install) ----------------------------------

    func snapshotLater(_ name: String, delay: Double = 0.7, panel: Bool = false) {
        guard !snapshotDir.isEmpty else { return }
        let target = URL(fileURLWithPath: "\(snapshotDir)/\(name).png")
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
            let view = panel ? self.panel.web : self.installer.web
            view.takeSnapshot(with: nil) { image, _ in
                if let tiff = image?.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) { try? rep.representation(using: .png, properties: [:])?.write(to: target) }
            }
        }
    }

    func runDemo() -> Bool {
        let steps: [[String: Any]] = [
            ["id": "ffprobe", "name": "ffprobe", "bytes": 28_317_701.0, "why": ""],
            ["id": "ffmpeg", "name": "ffmpeg", "bytes": 28_395_699.0, "why": ""],
            ["id": "deno", "name": "Deno", "bytes": 38_770_795.0, "why": ""],
            ["id": "meaning-model", "name": "Meaning model (multilingual-e5-small)", "bytes": 135_390_915.0, "why": ""],
            ["id": "whisper-model", "name": "Transcript model (Whisper small)", "bytes": 487_601_967.0, "why": ""]]
        let total = steps.reduce(0.0) { $0 + ($1["bytes"] as! Double) }
        func send(_ e: [String: Any]) { let k = e["event"] as! String; DispatchQueue.main.async { self.handle(e, k) } }
        if demo == "disk" {
            send(["event": "plan", "steps": steps, "total_bytes": total])
            send(["event": "precheck", "problems": [["kind": "disk", "message": "Magpiary needs about 2.2 GB free to install; this Mac has 1.1 GB. Free up some space and open it again."]]])
            snapshotLater("disk", delay: 1.5)
            return false
        }
        send(["event": "plan", "steps": steps, "total_bytes": total])
        snapshotLater("1-start", delay: 3.0)
        var done = 0.0
        var snapped = Set<Int>()
        for s in steps {
            send(["event": "step_start", "id": s["id"]!, "name": s["name"]!])
            let size = s["bytes"] as! Double
            var got = 0.0
            while got < size {
                got = min(size, got + 6_000_000)
                send(["event": "progress", "id": s["id"]!, "done": got, "total": size, "overall_done": done + got, "overall_total": total])
                let pct = Int((done + got) / total * 100)
                if pct >= 45 && !snapped.contains(45) {
                    snapped.insert(45)
                    snapshotLater("2-mid", delay: 3.5)
                    if demo == "offline" {
                        send(["event": "retry", "id": s["id"]!, "attempt": 1, "wait": 2.0, "reason": "offline"])
                        Thread.sleep(forTimeInterval: 0.5)
                        snapshotLater("4-retry", delay: 0.3)
                        Thread.sleep(forTimeInterval: 1.0)
                        send(["event": "step_error", "id": s["id"]!, "kind": "offline", "message": "Magpiary can’t reach the internet right now. Check your connection; what’s already downloaded is kept."])
                        snapshotLater("5-offline", delay: 1.0)
                        return false
                    }
                }
                Thread.sleep(forTimeInterval: 0.1)
            }
            done += size
            send(["event": "step_done", "id": s["id"]!])
        }
        send(["event": "finished", "ok": true])
        return true
    }
}

let app = NSApplication.shared
let shell = Shell()
app.delegate = shell
app.setActivationPolicy(.regular)
app.run()
