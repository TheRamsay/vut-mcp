import AppKit
import Foundation
import UserNotifications

struct NotificationArguments {
    let title: String
    let subtitle: String
    let message: String
    let identifier: String
    let sound: Bool
}

enum ArgumentError: Error, CustomStringConvertible {
    case missingValue(String)
    case unknown(String)
    case missingRequired(String)

    var description: String {
        switch self {
        case .missingValue(let flag):
            return "Missing value for \(flag)."
        case .unknown(let flag):
            return "Unknown argument \(flag)."
        case .missingRequired(let flag):
            return "Missing required argument \(flag)."
        }
    }
}

func parseArguments(_ arguments: [String]) throws -> NotificationArguments {
    var title: String?
    var subtitle: String?
    var message: String?
    var identifier: String?
    var sound = true
    var index = 1

    while index < arguments.count {
        let flag = arguments[index]
        switch flag {
        case "--title", "--subtitle", "--message", "--id":
            guard index + 1 < arguments.count else {
                throw ArgumentError.missingValue(flag)
            }
            let value = arguments[index + 1]
            switch flag {
            case "--title":
                title = value
            case "--subtitle":
                subtitle = value
            case "--message":
                message = value
            default:
                identifier = value
            }
            index += 2
        case "--no-sound":
            sound = false
            index += 1
        default:
            throw ArgumentError.unknown(flag)
        }
    }

    guard let title else { throw ArgumentError.missingRequired("--title") }
    guard let subtitle else { throw ArgumentError.missingRequired("--subtitle") }
    guard let message else { throw ArgumentError.missingRequired("--message") }
    guard let identifier else { throw ArgumentError.missingRequired("--id") }

    return NotificationArguments(
        title: title,
        subtitle: subtitle,
        message: message,
        identifier: identifier,
        sound: sound
    )
}

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    private let arguments: NotificationArguments

    init(arguments: NotificationArguments) {
        self.arguments = arguments
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let center = UNUserNotificationCenter.current()
        center.delegate = self

        center.requestAuthorization(options: [.alert, .sound, .badge]) { granted, error in
            if let error {
                self.finish(
                    code: 1,
                    message: "Notification authorization failed: \(error.localizedDescription)"
                )
                return
            }

            guard granted else {
                self.finish(
                    code: 2,
                    message: "Notifications are not authorized for VUT Studis Notifier."
                )
                return
            }

            self.deliver(with: center)
        }
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .list])
    }

    private func deliver(with center: UNUserNotificationCenter) {
        let content = UNMutableNotificationContent()
        content.title = arguments.title
        content.subtitle = arguments.subtitle
        content.body = arguments.message
        content.threadIdentifier = "vut-studis"
        if arguments.sound {
            content.sound = .default
        }

        let request = UNNotificationRequest(
            identifier: arguments.identifier,
            content: content,
            trigger: nil
        )

        center.add(request) { error in
            if let error {
                self.finish(
                    code: 1,
                    message: "Notification delivery failed: \(error.localizedDescription)"
                )
                return
            }

            self.finish(code: 0)
        }
    }

    private func finish(code: Int32, message: String? = nil) {
        if let message {
            fputs("\(message)\n", stderr)
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            exit(code)
        }
    }
}

func runNotifier(_ arguments: NotificationArguments) -> Int32 {
    let app = NSApplication.shared
    let delegate = AppDelegate(arguments: arguments)
    app.delegate = delegate
    app.setActivationPolicy(.accessory)
    app.run()
    return 0
}

func legacySendNotification(_ arguments: NotificationArguments) -> Int32 {
    let center = UNUserNotificationCenter.current()
    let semaphore = DispatchSemaphore(value: 0)
    var exitCode: Int32 = 0

    center.requestAuthorization(options: [.alert, .sound, .badge]) { granted, error in
        if let error {
            fputs("Notification authorization failed: \(error.localizedDescription)\n", stderr)
            exitCode = 1
            semaphore.signal()
            return
        }

        guard granted else {
            fputs("Notifications are not authorized for VUT Studis Notifier.\n", stderr)
            exitCode = 2
            semaphore.signal()
            return
        }

        let content = UNMutableNotificationContent()
        content.title = arguments.title
        content.subtitle = arguments.subtitle
        content.body = arguments.message
        content.threadIdentifier = "vut-studis"
        if arguments.sound {
            content.sound = .default
        }

        let request = UNNotificationRequest(
            identifier: arguments.identifier,
            content: content,
            trigger: nil
        )

        center.add(request) { error in
            if let error {
                fputs("Notification delivery failed: \(error.localizedDescription)\n", stderr)
                exitCode = 1
            }
            semaphore.signal()
        }
    }

    if semaphore.wait(timeout: .now() + 10) == .timedOut {
        fputs("Timed out while sending notification.\n", stderr)
        return 1
    }

    Thread.sleep(forTimeInterval: 0.4)
    return exitCode
}

do {
    let arguments = try parseArguments(CommandLine.arguments)
    exit(runNotifier(arguments))
} catch {
    fputs("\(error)\n", stderr)
    exit(64)
}
