#!/usr/bin/env swift
import AppKit
import Foundation
import PDFKit

struct Arguments {
    let pdf: String
    let outDir: String
    let startPage: Int
    let endPage: Int
    let dpi: Double
}

func value(after flag: String, in args: [String]) -> String? {
    guard let index = args.firstIndex(of: flag), index + 1 < args.count else {
        return nil
    }
    return args[index + 1]
}

func parseArguments() throws -> Arguments {
    let args = CommandLine.arguments
    guard
        let pdf = value(after: "--pdf", in: args),
        let outDir = value(after: "--out-dir", in: args),
        let start = Int(value(after: "--start-page", in: args) ?? ""),
        let end = Int(value(after: "--end-page", in: args) ?? ""),
        let dpi = Double(value(after: "--dpi", in: args) ?? "")
    else {
        throw NSError(domain: "render_pdf_pages_macos", code: 2, userInfo: [
            NSLocalizedDescriptionKey: "Usage: render_pdf_pages_macos.swift --pdf <path> --out-dir <dir> --start-page 1 --end-page 5 --dpi 200"
        ])
    }
    return Arguments(pdf: pdf, outDir: outDir, startPage: start, endPage: end, dpi: dpi)
}

func render(page: PDFPage, to outputURL: URL, dpi: Double) throws {
    let bounds = page.bounds(for: .mediaBox)
    let scale = dpi / 72.0
    let width = max(1, Int((bounds.width * scale).rounded()))
    let height = max(1, Int((bounds.height * scale).rounded()))
    let image = NSImage(size: NSSize(width: width, height: height))

    image.lockFocus()
    NSColor.white.setFill()
    NSBezierPath(rect: NSRect(x: 0, y: 0, width: width, height: height)).fill()
    guard let context = NSGraphicsContext.current?.cgContext else {
        throw NSError(domain: "render_pdf_pages_macos", code: 3, userInfo: [
            NSLocalizedDescriptionKey: "Could not create drawing context"
        ])
    }
    context.saveGState()
    context.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: context)
    context.restoreGState()
    image.unlockFocus()

    guard
        let tiff = image.tiffRepresentation,
        let bitmap = NSBitmapImageRep(data: tiff),
        let png = bitmap.representation(using: .png, properties: [:])
    else {
        throw NSError(domain: "render_pdf_pages_macos", code: 4, userInfo: [
            NSLocalizedDescriptionKey: "Could not encode PNG"
        ])
    }
    try png.write(to: outputURL)
}

do {
    let args = try parseArguments()
    let pdfURL = URL(fileURLWithPath: args.pdf)
    let outURL = URL(fileURLWithPath: args.outDir)
    try FileManager.default.createDirectory(at: outURL, withIntermediateDirectories: true)
    guard let document = PDFDocument(url: pdfURL) else {
        throw NSError(domain: "render_pdf_pages_macos", code: 5, userInfo: [
            NSLocalizedDescriptionKey: "Could not open PDF: \(args.pdf)"
        ])
    }
    let pageCount = document.pageCount
    if args.startPage < 1 || args.startPage > pageCount {
        throw NSError(domain: "render_pdf_pages_macos", code: 6, userInfo: [
            NSLocalizedDescriptionKey: "start page \(args.startPage) is outside 1...\(pageCount)"
        ])
    }
    let endPage = min(args.endPage, pageCount)
    for pageNumber in args.startPage...endPage {
        guard let page = document.page(at: pageNumber - 1) else {
            continue
        }
        let filename = String(format: "page-%03d.png", pageNumber)
        try render(page: page, to: outURL.appendingPathComponent(filename), dpi: args.dpi)
    }
    print("Rendered pages \(args.startPage)-\(endPage) to \(args.outDir)")
} catch {
    fputs("\(error.localizedDescription)\n", stderr)
    exit(1)
}
