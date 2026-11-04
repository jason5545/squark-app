import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let canvas: CGFloat = 1024
let center = CGPoint(x: canvas / 2, y: canvas / 2)
let space = CGColorSpace(name: CGColorSpace.sRGB)!
let white = CGColor(red: 1, green: 1, blue: 1, alpha: 1)
let coverage: CGFloat = 0.82

// steamac: Squark's icon. Squark is squawk (a transponder code, what a radar shows beside a
// target) plus quark, so a radar scope: the scope's rim, a range ring, the sweep with its
// fading trail, and a quark as the target it has just painted.
let scopeRadius: CGFloat = 430
let scopeWidth: CGFloat = 40
let ringRadius: CGFloat = 262
let ringWidth: CGFloat = 20
let hubRadius: CGFloat = 30
let sweepAngle: CGFloat = 38
let sweepLength: CGFloat = 404
let sweepWidth: CGFloat = 44
let trailSpan: CGFloat = 80
let trailAlpha: CGFloat = 0.6
let quarkAngle: CGFloat = 76
let quarkOrbit: CGFloat = 340
let quarkRadius: CGFloat = 66

enum Element: String, CaseIterable {
    case scope = "Scope"
    case sweep = "Sweep"
    case quark = "Quark"

    var fileName: String {
        rawValue.lowercased().replacingOccurrences(of: " ", with: "-") + ".png"
    }

    var fill: String {
        switch self {
        case .scope: "srgb:1.00000,1.00000,1.00000,1.00000"
        case .sweep: "srgb:0.43137,0.94902,0.76078,1.00000"
        case .quark: "srgb:1.00000,0.69020,0.12549,1.00000"
        }
    }
}

func point(angle degrees: CGFloat, radius: CGFloat) -> CGPoint {
    let angle = degrees * .pi / 180
    return CGPoint(x: center.x + radius * cos(angle), y: center.y + radius * sin(angle))
}

func makeContext(size: CGFloat) -> CGContext {
    let context = CGContext(
        data: nil,
        width: Int(size),
        height: Int(size),
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: space,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    )!
    context.setAllowsAntialiasing(true)
    context.interpolationQuality = .high
    return context
}

func circle(_ radius: CGFloat) -> CGRect {
    CGRect(
        x: center.x - radius,
        y: center.y - radius,
        width: radius * 2,
        height: radius * 2
    )
}

func draw(_ element: Element, into context: CGContext) {
    context.setStrokeColor(white)
    context.setFillColor(white)

    switch element {
    case .scope:
        context.setLineWidth(scopeWidth)
        context.strokeEllipse(in: circle(scopeRadius))
        context.setLineWidth(ringWidth)
        context.strokeEllipse(in: circle(ringRadius))
        context.fillEllipse(in: circle(hubRadius))

    case .sweep:
        // The sweep turns clockwise, so its trail lies counterclockwise of it, fading the
        // further back it lies.
        let steps = 140
        for step in 0..<steps {
            let back = CGFloat(step) / CGFloat(steps)
            let from = (sweepAngle + trailSpan * back) * .pi / 180
            let to = (sweepAngle + trailSpan * (back + 1 / CGFloat(steps))) * .pi / 180
            context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: trailAlpha * pow(1 - back, 1.6)))
            context.move(to: center)
            context.addArc(center: center, radius: sweepLength, startAngle: from, endAngle: to, clockwise: false)
            context.closePath()
            context.fillPath()
        }
        context.setLineWidth(sweepWidth)
        context.setLineCap(.round)
        context.move(to: center)
        context.addLine(to: point(angle: sweepAngle, radius: sweepLength))
        context.strokePath()

    case .quark:
        let at = point(angle: quarkAngle, radius: quarkOrbit)
        context.fillEllipse(in: CGRect(x: at.x - quarkRadius, y: at.y - quarkRadius,
                                       width: quarkRadius * 2, height: quarkRadius * 2))
    }
}

func render(_ elements: [Element]) -> CGImage {
    let context = makeContext(size: canvas)
    for element in elements {
        draw(element, into: context)
    }
    return context.makeImage()!
}

func inkBounds(_ image: CGImage) -> CGRect {
    let width = image.width
    let height = image.height
    var pixels = [UInt8](repeating: 0, count: width * height * 4)
    pixels.withUnsafeMutableBytes { buffer in
        let scan = CGContext(
            data: buffer.baseAddress,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: space,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )!
        scan.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    }
    var minX = width, minY = height, maxX = -1, maxY = -1
    for y in 0..<height {
        for x in 0..<width where pixels[(y * width + x) * 4 + 3] > 8 {
            if x < minX { minX = x }
            if x > maxX { maxX = x }
            if y < minY { minY = y }
            if y > maxY { maxY = y }
        }
    }
    guard maxX >= minX, maxY >= minY else {
        return CGRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height))
    }
    return CGRect(
        x: CGFloat(minX),
        y: CGFloat(minY),
        width: CGFloat(maxX - minX + 1),
        height: CGFloat(maxY - minY + 1)
    )
}

func normalized(_ image: CGImage, sharedInk ink: CGRect) -> CGImage {
    let scale = canvas * coverage / max(ink.width, ink.height)
    let context = makeContext(size: canvas)
    context.translateBy(x: canvas / 2, y: canvas / 2)
    context.scaleBy(x: scale, y: scale)
    context.translateBy(x: -ink.midX, y: -ink.midY)
    context.draw(image, in: CGRect(x: 0, y: 0, width: canvas, height: canvas))
    return context.makeImage()!
}

func write(_ image: CGImage, to url: URL) throws {
    guard
        let destination = CGImageDestinationCreateWithURL(
            url as CFURL,
            UTType.png.identifier as CFString,
            1,
            nil
        )
    else {
        throw CocoaError(.fileWriteUnknown)
    }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
        throw CocoaError(.fileWriteUnknown)
    }
}

func layer(_ element: Element) -> [String: Any] {
    ["fill": ["solid": element.fill], "image-name": element.fileName, "name": element.rawValue]
}

// Back to front: the scope, the sweep, the target on top.
let groups: [(name: String, elements: [Element], depth: Double, translucency: Double)] = [
    ("Scope", [.scope], 0.40, 0.35),
    ("Sweep", [.sweep], 0.70, 0.25),
    ("Quark", [.quark], 1.00, 0.15),
]

func group(_ entry: (name: String, elements: [Element], depth: Double, translucency: Double)) -> [String: Any] {
    [
        "blur-material": NSNull(),
        "layers": entry.elements.map(layer),
        "name": entry.name,
        "opacity": 1,
        "refractivity": ["depth": entry.depth, "enabled": true, "strength": 0.005],
        "shadow": ["kind": "neutral", "opacity": 0.5],
        "specular": "inside",
        "translucency": ["enabled": true, "value": entry.translucency],
    ]
}

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write("usage: icon <output.icon>\n".data(using: .utf8)!)
    exit(2)
}

let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let assets = root.appendingPathComponent("Assets", isDirectory: true)
try? FileManager.default.removeItem(at: root)
try FileManager.default.createDirectory(at: assets, withIntermediateDirectories: true)

let sharedInk = inkBounds(render(Element.allCases))
for element in Element.allCases {
    let layer = normalized(render([element]), sharedInk: sharedInk)
    try write(layer, to: assets.appendingPathComponent(element.fileName))
}

let document: [String: Any] = [
    "features": ["refractivity", "specular-location"],
    "fill": [
        "linear-gradient": [
            "srgb:0.05098,0.29020,0.38824,1.00000",
            "srgb:0.02353,0.08627,0.14902,1.00000",
        ]
    ],
    "groups": groups.reversed().map(group),
    "supported-platforms": ["circles": ["watchOS"], "squares": "shared"],
]
try JSONSerialization
    .data(withJSONObject: document, options: [.prettyPrinted, .sortedKeys])
    .write(to: root.appendingPathComponent("icon.json"))
