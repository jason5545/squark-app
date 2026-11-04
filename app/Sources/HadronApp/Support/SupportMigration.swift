// steamac: this fork became Squark on 2026-11-04. A Mac that ran it as Hadron keeps its data
// under Hadron's names, so the first start of Squark moves it before anything reads it:
// ~/Library/Application Support/hadron and ~/Library/Caches/hadron, the record of modified
// Steam bundles, the settings Hadron kept under nl.nhsd.hadron, and the path of the app that
// Steam starts prefix rebuilds with. The old support folder is left as a link to the new one,
// so a Steam still injecting hadron.dylib, and the run scripts it wrote, keep working until
// Install replaces them.

import Foundation

enum SupportMigration {

    static let legacyBundleIdentifier = "nl.nhsd.hadron"
    static let legacyModificationsName = "hadron-steam-bundles.json"
    static let defaultsMarker = "migratedFromHadron"

    struct Outcome: Equatable {
        var moved: [String] = []
        var failures: [String] = []
    }

    @discardableResult
    static func run(
        home: URL = SupportPaths.home,
        defaults: UserDefaults = .standard,
        legacyDefaults: [String: Any]? = UserDefaults.standard.persistentDomain(forName: legacyBundleIdentifier),
        executable: URL? = Bundle.main.executableURL
    ) -> Outcome {
        var outcome = Outcome()
        let library = home.appending(path: "Library")
        let support = library.appending(path: "Application Support")
        move(support.appending(path: SupportPaths.legacySupportDirName),
             to: support.appending(path: SupportPaths.supportDirName), leavingLink: true, into: &outcome)
        move(library.appending(path: "Caches/\(SupportPaths.legacySupportDirName)"),
             to: library.appending(path: "Caches/\(SupportPaths.supportDirName)"), leavingLink: false, into: &outcome)
        move(support.appending(path: legacyModificationsName),
             to: support.appending(path: SteamModifications.fileName), leavingLink: false, into: &outcome)
        copyDefaults(legacyDefaults, into: defaults)
        if let executable {
            repointRebuildApp(in: support.appending(path: SupportPaths.supportDirName), to: executable, into: &outcome)
        }
        // AppLog starts later, in the app's init, and drops notes made before it.
        pending = outcome.moved.map { "migration: \($0)" } + outcome.failures.map { "migration failed: \($0)" }
        return outcome
    }

    private nonisolated(unsafe) static var pending: [String] = []

    static func logPending() {
        for line in pending { AppLog.note(line) }
        pending = []
    }

    // Moves a Hadron folder or file to its Squark name, unless Squark already has one or the
    // old name is the link an earlier run left.
    static func move(_ old: URL, to new: URL, leavingLink: Bool, into outcome: inout Outcome) {
        let files = FileManager.default
        let oldPath = old.path(percentEncoded: false)
        let newPath = new.path(percentEncoded: false)
        guard let type = try? files.attributesOfItem(atPath: oldPath)[.type] as? FileAttributeType,
              type != .typeSymbolicLink
        else { return }
        guard !files.fileExists(atPath: newPath) else {
            outcome.failures.append("\(oldPath) is left in place, \(newPath) already exists")
            return
        }
        guard rename(oldPath, newPath) == 0 else {
            outcome.failures.append("\(oldPath) -> \(newPath): \(String(cString: strerror(errno)))")
            return
        }
        outcome.moved.append("\(oldPath) -> \(newPath)")
        if leavingLink {
            do {
                try files.createSymbolicLink(atPath: oldPath, withDestinationPath: new.lastPathComponent)
            } catch {
                outcome.failures.append("link \(oldPath): \(error.localizedDescription)")
            }
        }
    }

    static func copyDefaults(_ legacy: [String: Any]?, into defaults: UserDefaults) {
        guard !defaults.bool(forKey: defaultsMarker) else { return }
        for (key, value) in legacy ?? [:] where defaults.object(forKey: key) == nil {
            defaults.set(value, forKey: key)
        }
        defaults.set(true, forKey: defaultsMarker)
    }

    // The run script starts prefix rebuilds with the app this file names. Install writes it
    // again; until then it still names Hadron.app, which is gone.
    static func repointRebuildApp(in support: URL, to executable: URL, into outcome: inout Outcome) {
        let record = support.appending(path: RebuildPrefixCommand.executableRecord)
        guard let recorded = try? String(contentsOf: record, encoding: .utf8),
              recorded.contains("/Hadron.app/")
        else { return }
        do {
            try Data(executable.path(percentEncoded: false).utf8).write(to: record, options: .atomic)
            outcome.moved.append("\(record.path(percentEncoded: false)) now names \(executable.path(percentEncoded: false))")
        } catch {
            outcome.failures.append("\(record.path(percentEncoded: false)): \(error.localizedDescription)")
        }
    }
}
