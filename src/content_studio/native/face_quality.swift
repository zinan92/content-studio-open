// 本机给候选帧打分：macOS Vision 的人脸拍摄质量（Apple 专门用来从连拍里挑最好那张）。
// 用法：swift face_quality.swift <图1> <图2> ...
// 每张一行：<路径>\t<人脸数>\t<最好那张脸的质量 0–1，没脸是 -1>
import Foundation
import Vision

for path in CommandLine.arguments.dropFirst() {
    let url = URL(fileURLWithPath: path)
    let req = VNDetectFaceCaptureQualityRequest()
    let handler = VNImageRequestHandler(url: url)
    var faces = 0
    var best: Float = -1
    if (try? handler.perform([req])) != nil, let results = req.results {
        faces = results.count
        for face in results { best = max(best, face.faceCaptureQuality ?? -1) }
    }
    print("\(path)\t\(faces)\t\(best)")
}
