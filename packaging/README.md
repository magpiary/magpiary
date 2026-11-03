# Packaging

- `install.sh` (repository root): the one-line installer. No Homebrew needed.
- `magpiary.rb`: the Homebrew formula, published at M8 in `magpiary/homebrew-tap`.

## Testing the formula locally

```sh
git archive --prefix=magpiary-0.1.0/ -o /tmp/magpiary-0.1.0.tar.gz HEAD
brew tap-new --no-git magpiary/local
# copy magpiary.rb into $(brew --repository magpiary/local)/Formula/, with url "file:///tmp/magpiary-0.1.0.tar.gz"
# and that file's sha256, then:
brew install magpiary/local/magpiary && brew test magpiary/local/magpiary
brew uninstall magpiary && brew untap magpiary/local
```

Do not set `HOMEBREW_NO_INSTALL_FROM_API`: it makes Homebrew clone all of homebrew-core (over 1 GB).

A formula without bottles builds from source, which needs up-to-date Xcode Command Line Tools (Homebrew refused
with version 16.4; it worked with 27.0). At M8 the tap should publish bottles (built by GitHub Actions with
`brew test-bot`), so users never need them.

Installing it also upgrades the user's Homebrew dependencies (uv, ffmpeg, sqlite...) to current versions, and
`brew uninstall magpiary` removes Deno and Python 3.12 again if nothing else uses them.

The formula in the repo keeps an all-zero SHA-256 (the archive contains it). The release pipeline writes `dist/magpiary.rb` with the real checksum; copy that file into the tap after tagging.
