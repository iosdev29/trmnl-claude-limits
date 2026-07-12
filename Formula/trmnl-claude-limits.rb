class TrmnlClaudeLimits < Formula
  desc "Push Claude Code usage limits to your TRMNL e-ink display"
  homepage "https://github.com/iosdev29/trmnl-claude-limits"
  license "MIT"
  head "https://github.com/iosdev29/trmnl-claude-limits.git", branch: "main"

  depends_on "python@3.12"

  def install
    libexec.install "scripts/install.py"
    libexec.install "scripts/push_usage.py"

    python = Formula["python@3.12"].opt_bin/"python3"

    (bin/"trmnl-claude-limits").write <<~SH
      #!/usr/bin/env bash
      set -e
      case "${1:-}" in
        push)
          shift
          exec "#{python}" "#{libexec}/push_usage.py" "$@"
          ;;
        *)
          exec "#{python}" "#{libexec}/install.py" "$@"
          ;;
      esac
    SH
    chmod 0755, bin/"trmnl-claude-limits"
  end

  def caveats
    <<~EOS
      Finish setup:
        trmnl-claude-limits

      You'll be prompted for your TRMNL webhook URL, then a LaunchAgent runs
      every 10 minutes. Manual push:
        trmnl-claude-limits push --dry-run
      Uninstall the scheduler (keeps the formula):
        trmnl-claude-limits --uninstall
    EOS
  end

  test do
    assert_match "webhook", shell_output("#{bin}/trmnl-claude-limits --help")
  end
end
