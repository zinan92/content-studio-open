// 本机读图里的字：macOS Vision 文字识别（中文 + 英文）。证据截图拿来查有没有隐私（AppID、密钥、手机号）、字够不够清楚。
// 用法：swift ocr_text.swift <图1> <图2> ...
// 每张图一段：第一行 "### <路径>"，后面每行一行识别出来的字。
import Foundation
import Vision

for path in CommandLine.arguments.dropFirst() {
    print("### \(path)")
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["zh-Hans", "en-US"]
    req.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(url: URL(fileURLWithPath: path))
    if (try? handler.perform([req])) != nil, let results = req.results {
        for r in results {
            if let top = r.topCandidates(1).first { print(top.string) }
        }
    }
}
