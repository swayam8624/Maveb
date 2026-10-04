import Foundation

struct SparseCoverageReport: Decodable, Equatable {
    let passed: Bool
    let inputImages: Int
    let registeredImages: Int
    let registrationRatio: Double
    let trackedPoints: Int
    let meanTrackLength: Double
    let connectedImages: Int
    let connectedImageRatio: Double
    let baselineDiagonal: Double
    let maximumViewAngleDegrees: Double
    let issues: [String]
}

struct TrainingCheckpoint: Identifiable, Equatable, Sendable {
    let iteration: Int
    let url: URL
    let bytes: UInt64
    var id: String { url.path }

    static func discover(in jobURL: URL) throws -> [TrainingCheckpoint] {
        let exports = jobURL.appendingPathComponent("exports", isDirectory: true)
        let urls = try FileManager.default.contentsOfDirectory(
            at: exports, includingPropertiesForKeys: [.fileSizeKey, .isRegularFileKey],
            options: [.skipsHiddenFiles])
        return try urls.compactMap { url in
            let name = url.deletingPathExtension().lastPathComponent
            guard url.pathExtension.lowercased() == "ply", name.hasPrefix("checkpoint_") else {
                return nil
            }
            let digits = name.dropFirst("checkpoint_".count)
            guard !digits.isEmpty, digits.allSatisfy(\.isNumber), let iteration = Int(digits),
                  iteration > 0 else { return nil }
            let values = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
            guard values.isRegularFile == true, let size = values.fileSize, size > 0 else { return nil }
            return TrainingCheckpoint(iteration: iteration, url: url, bytes: UInt64(size))
        }.sorted { left, right in
            left.iteration == right.iteration ? left.url.path < right.url.path
                                              : left.iteration < right.iteration
        }
    }
}
