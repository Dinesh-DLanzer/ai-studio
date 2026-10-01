// Usage: swift lastframe.swift <video.mp4> <out.png>   (macOS; used by vidad.py when ffmpeg is missing)
import AVFoundation
import AppKit
let asset = AVAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
let g = AVAssetImageGenerator(asset: asset); g.appliesPreferredTrackTransform = true
g.requestedTimeToleranceBefore = .zero; g.requestedTimeToleranceAfter = .zero
let dur = CMTimeGetSeconds(asset.duration)
guard let cg = try? g.copyCGImage(at: CMTime(seconds: max(dur - 0.06, 0), preferredTimescale: 600), actualTime: nil) else { exit(1) }
let rep = NSBitmapImageRep(cgImage: cg)
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
