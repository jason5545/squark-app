import Foundation
import Testing

@testable import HadronApp

// steamac: the move from Hadron's names to Squark's (SupportMigration, and Steam still
// injecting hadron.dylib until Install replaces it).
@Suite("Migration from Hadron")
struct SupportMigrationTests {

    private func scratch() throws -> URL {
        let root = URL.temporaryDirectory.appending(path: "squark-migrate-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private func path(_ url: URL) -> String { url.path(percentEncoded: false) }

    private func run(_ home: URL, defaults: UserDefaults, legacy: [String: Any]? = nil,
                     executable: URL? = nil) -> SupportMigration.Outcome {
        SupportMigration.run(home: home, defaults: defaults, legacyDefaults: legacy, executable: executable)
    }

    private func freshDefaults() -> UserDefaults {
        let name = "squark-migrate-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        defaults.removePersistentDomain(forName: name)
        return defaults
    }

    @Test("Hadron's folders and Steam record move to Squark's names, and the old folder links to the new")
    func movesEverything() throws {
        let home = try scratch()
        defer { try? FileManager.default.removeItem(at: home) }
        let support = home.appending(path: "Library/Application Support")
        let caches = home.appending(path: "Library/Caches")
        try FileManager.default.createDirectory(at: support.appending(path: "hadron/runners/wine-x"), withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: caches.appending(path: "hadron/winetricks"), withIntermediateDirectories: true)
        try Data("tools".utf8).write(to: support.appending(path: "hadron/tools"))
        try Data("[]".utf8).write(to: support.appending(path: "hadron-steam-bundles.json"))

        let outcome = run(home, defaults: freshDefaults())

        #expect(outcome.failures.isEmpty)
        #expect(outcome.moved.count == 3)
        #expect(try String(contentsOf: support.appending(path: "squark/tools"), encoding: .utf8) == "tools")
        #expect(FileManager.default.fileExists(atPath: path(support.appending(path: "squark/runners/wine-x"))))
        #expect(FileManager.default.fileExists(atPath: path(caches.appending(path: "squark/winetricks"))))
        #expect(!FileManager.default.fileExists(atPath: path(caches.appending(path: "hadron"))))
        #expect(FileManager.default.fileExists(atPath: path(support.appending(path: SteamModifications.fileName))))
        #expect(!FileManager.default.fileExists(atPath: path(support.appending(path: "hadron-steam-bundles.json"))))
        #expect(try FileManager.default.destinationOfSymbolicLink(atPath: path(support.appending(path: "hadron"))) == "squark")
        // Through the link, an old dylib in Steam still finds what it reads.
        #expect(try String(contentsOf: support.appending(path: "hadron/tools"), encoding: .utf8) == "tools")
    }

    @Test("A second start finds the link and moves nothing")
    func runsOnce() throws {
        let home = try scratch()
        defer { try? FileManager.default.removeItem(at: home) }
        let support = home.appending(path: "Library/Application Support")
        try FileManager.default.createDirectory(at: support.appending(path: "hadron"), withIntermediateDirectories: true)
        let defaults = freshDefaults()

        _ = run(home, defaults: defaults)
        let again = run(home, defaults: defaults)

        #expect(again == SupportMigration.Outcome())
    }

    @Test("A Squark folder that already exists is not replaced, and the Hadron one stays")
    func keepsExisting() throws {
        let home = try scratch()
        defer { try? FileManager.default.removeItem(at: home) }
        let support = home.appending(path: "Library/Application Support")
        try FileManager.default.createDirectory(at: support.appending(path: "hadron"), withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: support.appending(path: "squark"), withIntermediateDirectories: true)
        try Data("new".utf8).write(to: support.appending(path: "squark/tools"))

        let outcome = run(home, defaults: freshDefaults())

        #expect(outcome.moved.isEmpty)
        #expect(outcome.failures.count == 1)
        #expect(try String(contentsOf: support.appending(path: "squark/tools"), encoding: .utf8) == "new")
        let type = try FileManager.default.attributesOfItem(atPath: path(support.appending(path: "hadron")))[.type] as? FileAttributeType
        #expect(type == .typeDirectory)
    }

    @Test("Hadron's settings are copied once, without overwriting Squark's")
    func copiesDefaults() {
        let defaults = freshDefaults()
        defaults.set("/Volumes/Games/Steam.app", forKey: "kept")

        SupportMigration.copyDefaults(["steamAppPath": "/Applications/Steam.app", "kept": "old"], into: defaults)
        SupportMigration.copyDefaults(["late": "1"], into: defaults)

        #expect(defaults.string(forKey: "steamAppPath") == "/Applications/Steam.app")
        #expect(defaults.string(forKey: "kept") == "/Volumes/Games/Steam.app")
        #expect(defaults.object(forKey: "late") == nil)
    }

    @Test("The rebuild app record that names Hadron.app is pointed at this app")
    func repointsRebuildApp() throws {
        let home = try scratch()
        defer { try? FileManager.default.removeItem(at: home) }
        let support = home.appending(path: "Library/Application Support")
        let record = support.appending(path: "hadron/\(RebuildPrefixCommand.executableRecord)")
        try FileManager.default.createDirectory(at: record.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("/Applications/Hadron.app/Contents/MacOS/HadronApp".utf8).write(to: record)
        let squark = URL(filePath: "/Applications/Squark.app/Contents/MacOS/HadronApp")

        _ = run(home, defaults: freshDefaults(), executable: squark)

        let moved = support.appending(path: "squark/\(RebuildPrefixCommand.executableRecord)")
        #expect(try String(contentsOf: moved, encoding: .utf8) == path(squark))
    }

    private func steam(insert: String?, files: [String]) throws -> (root: URL, app: URL) {
        let root = try scratch()
        let app = root.appending(path: "Steam.app")
        let macOS = app.appending(path: "Contents/MacOS")
        try FileManager.default.createDirectory(at: macOS, withIntermediateDirectories: true)
        for name in files { try Data("dylib".utf8).write(to: macOS.appending(path: name)) }
        var plist: [String: Any] = ["CFBundleIdentifier": "com.valvesoftware.steam"]
        if let insert {
            plist[SteamBundle.environmentKey] = [SteamBundle.insertKey: path(macOS.appending(path: insert))]
        }
        try SteamBundle.writeInfoPlist(plist, at: app.appending(path: "Contents/Info.plist"))
        return (root, app)
    }

    @Test("A Steam injecting Hadron's dylib needs an install, it is not someone else's")
    func legacyInsertIsOurs() throws {
        let (root, app) = try steam(insert: "hadron.dylib", files: ["hadron.dylib"])
        defer { try? FileManager.default.removeItem(at: root) }
        let plist = app.appending(path: "Contents/Info.plist")

        #expect(SteamBundle.deployment(bundledVersion: "0.2.0", app: app, versionFile: root.appending(path: "v")) == .notInstalled)
        #expect(throws: Never.self) {
            try SteamInstaller.assertInsertIsDeployedOrAbsent(at: plist, dylib: SupportPaths.Steam.deployedDylib(inBundle: app))
        }
        #expect(try SteamModifications.inspect(app) == .modified)
    }

    @Test("A dylib by another name is still foreign")
    func otherInsertIsForeign() throws {
        let (root, app) = try steam(insert: "other.dylib", files: ["other.dylib"])
        defer { try? FileManager.default.removeItem(at: root) }

        #expect(SteamBundle.deployment(bundledVersion: "0.2.0", app: app, versionFile: root.appending(path: "v"))
            == .foreign(insert: path(app.appending(path: "Contents/MacOS/other.dylib"))))
    }

    @Test("Installing removes the hadron.dylib left beside squark.dylib")
    func removesLegacyDylib() throws {
        let (root, app) = try steam(insert: nil, files: ["hadron.dylib", "squark.dylib", "steam_osx"])
        defer { try? FileManager.default.removeItem(at: root) }
        let macOS = app.appending(path: "Contents/MacOS")

        try SteamInstaller.removeLegacyDylibs(beside: macOS.appending(path: SupportPaths.dylibName))

        #expect(!FileManager.default.fileExists(atPath: path(macOS.appending(path: "hadron.dylib"))))
        #expect(FileManager.default.fileExists(atPath: path(macOS.appending(path: "squark.dylib"))))
        #expect(FileManager.default.fileExists(atPath: path(macOS.appending(path: "steam_osx"))))
    }
}
