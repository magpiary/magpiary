# Homebrew formula for Magpiary. Published at M8 in the tap magpiary/homebrew-tap, so that
#   brew install magpiary/tap/magpiary
# works. Until then it is tested locally (see packaging/README.md). At each release, `url` and `sha256` change.
# The checksum below stays zero in the repo: the archive contains this file, so it cannot hold its own checksum.
# The release pipeline writes the tap copy with the real one (dist/magpiary.rb); publish that file to the tap.
class Magpiary < Formula
  desc "Turns posts shared from your iPhone into a searchable library on your Mac"
  homepage "https://github.com/magpiary/magpiary"
  url "https://github.com/magpiary/magpiary/archive/refs/tags/v0.1.6.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"

  depends_on "deno" # YouTube needs a JavaScript runtime
  depends_on "ffmpeg"
  depends_on :macos
  depends_on "python@3.12"
  depends_on "uv"

  def install
    python = Formula["python@3.12"].opt_bin/"python3.12"
    system "uv", "venv", "--python", python, libexec
    # yt-dlp lives beside Magpiary, which keeps it up to date daily (sites change often)
    system "uv", "pip", "install", "--python", libexec/"bin/python", buildpath, "yt-dlp"
    bin.install_symlink libexec/"bin/magpiary"
  end

  def caveats
    <<~EOS
      To finish (downloads about 600 MB of models, then starts the background service):
        magpiary models install
        magpiary service install
      Then open the address that `magpiary service status` shows (usually http://localhost:8765/) and follow the setup guide.
      Updates: brew upgrade magpiary
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/magpiary --version")
    assert_match "already here", shell_output("#{bin}/magpiary tools install")
  end
end
