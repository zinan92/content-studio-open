// 中文分词：macOS NaturalLanguage 的 NLTokenizer，给封面排字找「可以断行的地方」。
// 用法：swift word_breaks.swift <一行文字>
// 输出：每个词一行，「起点\t终点」（按 Unicode 标量计数，和 Python 的字符下标一致）。
import Foundation
import NaturalLanguage

let text = CommandLine.arguments.dropFirst().joined(separator: " ")
let tok = NLTokenizer(unit: .word)
tok.string = text
tok.setLanguage(.simplifiedChinese)
tok.enumerateTokens(in: text.startIndex..<text.endIndex) { range, _ in
    let a = text.unicodeScalars.distance(from: text.unicodeScalars.startIndex, to: range.lowerBound.samePosition(in: text.unicodeScalars)!)
    let b = text.unicodeScalars.distance(from: text.unicodeScalars.startIndex, to: range.upperBound.samePosition(in: text.unicodeScalars)!)
    print("\(a)\t\(b)")
    return true
}
