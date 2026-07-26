# Scheduled routine shell environment

`routine_runner.sh` sets `ZDOTDIR` to this directory before starting a
headless runtime. Keep zsh startup dotfiles out of this directory. This stops
unattended model shell commands from loading interactive aliases, overriding
`$OV`, or inheriting credentials exported by a personal `~/.zshrc`.
