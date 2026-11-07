import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let canvas: CGFloat = 1024
let center = CGPoint(x: canvas / 2, y: canvas / 2)
let space = CGColorSpace(name: CGColorSpace.sRGB)!
let white = CGColor(red: 1, green: 1, blue: 1, alpha: 1)
let coverage: CGFloat = 0.82

// steamac: Squark's icon. Squark runs Windows games, not one game, so the diamond of a gamepad's
// four face buttons. The top one is a quark, amber, and the ring around it its superpartner: a
// squark is the superpartner of a quark.
let buttonOffset: CGFloat = 262
let buttonRadius: CGFloat = 134
let haloGap: CGFloat = 40
let haloWidth: CGFloat = 22

enum Element: String, CaseIterable {
    case buttons = "Buttons"
    case halo = "Halo"
    case quark = "Quark"

    var fileName: String {
        rawValue.lowercased().replacingOccurrences(of: " ", with: "-") + ".png"
    }

    var fill: String {
        switch self {
        case .buttons: "srgb:0.43137,0.94902,0.76078,1.00000"
        case .halo: "srgb:1.00000,1.00000,1.00000,1.00000"
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

func circle(_ radius: CGFloat, at middle: CGPoint = center) -> CGRect {
    CGRect(
        x: middle.x - radius,
        y: middle.y - radius,
        width: radius * 2,
        height: radius * 2
    )
}

func draw(_ element: Element, into context: CGContext) {
    context.setStrokeColor(white)
    context.setFillColor(white)
    // Up is 90 degrees: the context's origin is at the bottom left.
    let top = point(angle: 90, radius: buttonOffset)

    switch element {
    case .buttons:
        for angle: CGFloat in [0, 180, 270] {
            context.fillEllipse(in: circle(buttonRadius, at: point(angle: angle, radius: buttonOffset)))
        }

    case .halo:
        context.setLineWidth(haloWidth)
        context.strokeEllipse(in: circle(buttonRadius + haloGap, at: top))

    case .quark:
        context.fillEllipse(in: circle(buttonRadius, at: top))
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

// Back to front: the three buttons, the superpartner's ring, the quark on top.
let groups: [(name: String, elements: [Element], depth: Double, translucency: Double)] = [
    ("Buttons", [.buttons], 0.50, 0.45),
    ("Halo", [.halo], 0.70, 0.30),
    ("Quark", [.quark], 1.00, 0.10),
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
