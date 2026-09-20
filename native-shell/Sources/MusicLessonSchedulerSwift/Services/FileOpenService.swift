import AppKit
import Foundation
import UniformTypeIdentifiers

enum DesktopFileKind: String {
    case assessmentData
    case lectureCSV
    case schedulerSource
    case sourceData
    case workbook

    var contentTypes: [UTType] {
        switch self {
        case .assessmentData:
            return [
                .commaSeparatedText,
                UTType(filenameExtension: "xlsx") ?? .spreadsheet,
            ]
        case .lectureCSV:
            return [.commaSeparatedText]
        case .schedulerSource, .sourceData:
            return [
                .commaSeparatedText,
                UTType(filenameExtension: "xlsx") ?? .spreadsheet,
            ]
        case .workbook:
            return [UTType(filenameExtension: "xlsx") ?? .spreadsheet]
        }
    }

    var prompt: String {
        switch self {
        case .assessmentData: return "Choose Assessment Data"
        case .lectureCSV: return "Choose Lecture CSV"
        case .schedulerSource: return "Choose Scheduling Source"
        case .sourceData: return "Choose Canonical Source Data"
        case .workbook: return "Choose Scheduling Workbook"
        }
    }

    var mimeType: String {
        switch self {
        case .assessmentData: return "application/octet-stream"
        case .lectureCSV: return "text/csv"
        case .schedulerSource, .sourceData: return "application/octet-stream"
        case .workbook: return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        }
    }
}

@MainActor
final class FileOpenService {
    func choose(kind rawKind: String) throws -> [String: Any] {
        guard let kind = DesktopFileKind(rawValue: rawKind) else {
            throw FileOpenError.unsupportedKind
        }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = kind.contentTypes
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.prompt = kind.prompt
        panel.resolvesAliases = true

        guard panel.runModal() == .OK, let url = panel.url else {
            return ["selected": false]
        }
        let data = try Data(contentsOf: url, options: [.mappedIfSafe])
        return [
            "selected": true,
            "name": url.lastPathComponent,
            "location": url.deletingLastPathComponent().path,
            "mimeType": kind.mimeType,
            "size": data.count,
            "dataBase64": data.base64EncodedString(),
        ]
    }
}

private enum FileOpenError: LocalizedError {
    case unsupportedKind

    var errorDescription: String? {
        "This file selection request is not supported."
    }
}
