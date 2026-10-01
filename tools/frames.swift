// Usage: swift frames.swift <video.mp4> <outdir> <count>   (macOS)  Decodes sequentially and saves <count> evenly spaced frames
// across the WHOLE clip (seeking past ~4s is unreliable, so this reads frame by frame).
import AVFoundation
import AppKit
import CoreImage
let asset = AVAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
let out = CommandLine.arguments[2]
let n = Int(CommandLine.arguments[3])!
let dur = CMTimeGetSeconds(asset.duration)
let targets = (0..<n).map { (Double($0) + 0.5) / Double(n) * dur }
guard let track = asset.tracks(withMediaType: .video).first, let reader = try? AVAssetReader(asset: asset) else { exit(1) }
let o = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
reader.add(o); reader.startReading()
let ctx = CIContext(); var idx = 0
while idx < n, let s = o.copyNextSampleBuffer() {
  let t = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(s))
  if t >= targets[idx], let pb = CMSampleBufferGetImageBuffer(s) {
    let ci = CIImage(cvPixelBuffer: pb)
    if let cg = ctx.createCGImage(ci, from: ci.extent) {
      let name = String(format: "%@/f%02d_%.1fs.png", out, idx, t)
      try? NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: name))
      print(name)
    }
    idx += 1
  }
}
