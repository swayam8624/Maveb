#include <aether/capture/CaptureValidator.hpp>

#include <iomanip>
#include <iostream>
#include <string_view>

namespace {
std::string escapeJson(std::string_view value) {
    std::string result;
    for (const char character : value) {
        switch (character) {
        case '\\': result += "\\\\"; break;
        case '"': result += "\\\""; break;
        case '\n': result += "\\n"; break;
        case '\r': result += "\\r"; break;
        case '\t': result += "\\t"; break;
        default: result += character;
        }
    }
    return result;
}

void optionalNumber(const std::optional<double>& value) {
    if (value) std::cout << *value;
    else std::cout << "null";
}

int usage() {
    std::cout << "Usage: aether-capture validate <images-directory> [--json]"
                 " [--minimum-images N] [--max-analysis-dimension N]\n";
    return 0;
}
} // namespace

int main(int argc, char** argv) {
    bool json = false;
    std::filesystem::path input;
    aether::capture::ValidationOptions options;
    if (argc >= 2 && (std::string_view(argv[1]) == "--help" || std::string_view(argv[1]) == "-h"))
        return usage();
    if (argc < 3 || std::string_view(argv[1]) != "validate") {
        usage();
        return 2;
    }
    input = argv[2];
    try {
        for (int index = 3; index < argc; ++index) {
            const std::string_view argument(argv[index]);
            if (argument == "--json") json = true;
            else if (argument == "--minimum-images" && index + 1 < argc)
                options.minimumImages = std::stoull(argv[++index]);
            else if (argument == "--max-analysis-dimension" && index + 1 < argc)
                options.analysisMaximumDimension = std::stoull(argv[++index]);
            else {
                std::cerr << "Unexpected or incomplete argument: " << argument << '\n';
                return 2;
            }
        }
    } catch (const std::exception& error) {
        std::cerr << "Invalid numeric option: " << error.what() << '\n';
        return 2;
    }
    if (options.minimumImages == 0 || options.analysisMaximumDimension < 32 ||
        options.analysisMaximumDimension > 8192) {
        std::cerr << "Numeric options are outside supported bounds\n";
        return 2;
    }

    const auto report = aether::capture::validateCapture(input, options);
    std::cout << std::setprecision(8);
    if (json) {
        std::cout << "{\"schemaVersion\":1,\"valid\":" << (report.valid() ? "true" : "false")
                  << ",\"root\":\"" << escapeJson(report.root.string()) << "\",\"summary\":{"
                  << "\"imageCount\":" << report.images.size() << ",\"sourceBytes\":"
                  << report.sourceBytes << ",\"estimatedWorkingBytes\":"
                  << report.estimatedWorkingBytes << ",\"medianSharpness\":"
                  << report.medianSharpness << ",\"exposureSpreadStops\":"
                  << report.exposureSpreadStops << "},\"images\":[";
        for (std::size_t index = 0; index < report.images.size(); ++index) {
            const auto& image = report.images[index];
            if (index) std::cout << ',';
            std::cout << "{\"path\":\"" << escapeJson(image.path.string()) << "\",\"bytes\":"
                      << image.fileBytes << ",\"width\":" << image.width << ",\"height\":"
                      << image.height << ",\"meanLuminance\":" << image.meanLuminance
                      << ",\"luminanceDeviation\":" << image.luminanceDeviation
                      << ",\"sharpness\":" << image.sharpness << ",\"exposureSeconds\":";
            optionalNumber(image.exposureSeconds);
            std::cout << ",\"fNumber\":"; optionalNumber(image.fNumber);
            std::cout << ",\"iso\":"; optionalNumber(image.iso);
            std::cout << ",\"focalLengthMillimetres\":"; optionalNumber(image.focalLengthMillimetres);
            std::cout << ",\"cameraMake\":\"" << escapeJson(image.cameraMake)
                      << "\",\"cameraModel\":\"" << escapeJson(image.cameraModel) << "\"}";
        }
        std::cout << "],\"issues\":[";
        for (std::size_t index = 0; index < report.issues.size(); ++index) {
            const auto& issue = report.issues[index];
            if (index) std::cout << ',';
            std::cout << "{\"severity\":\""
                      << (issue.severity == aether::capture::CaptureIssue::Severity::error ? "error" : "warning")
                      << "\",\"code\":\"" << escapeJson(issue.code) << "\",\"message\":\""
                      << escapeJson(issue.message) << "\",\"path\":";
            if (issue.path) std::cout << '"' << escapeJson(issue.path->string()) << '"';
            else std::cout << "null";
            std::cout << '}';
        }
        std::cout << "]}\n";
    } else {
        std::cout << (report.valid() ? "Capture validation passed" : "Capture validation failed")
                  << "\nImages: " << report.images.size() << "\nSource bytes: " << report.sourceBytes
                  << "\nEstimated working bytes: " << report.estimatedWorkingBytes
                  << "\nMedian sharpness: " << report.medianSharpness
                  << "\nExposure spread: " << report.exposureSpreadStops << " stops\n";
        for (const auto& issue : report.issues)
            std::cout << (issue.severity == aether::capture::CaptureIssue::Severity::error ? "ERROR " : "WARN ")
                      << issue.code << ": " << issue.message
                      << (issue.path ? " [" + issue.path->string() + "]" : "") << '\n';
    }
    return report.valid() ? 0 : 3;
}
