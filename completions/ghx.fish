# Fish completion for ghx — Intelligent GitHub CLI account switcher

# Disable file completions by default
complete -c ghx -f

# ghx-specific subcommands
complete -c ghx -n '__fish_use_subcommand' -a 'status' -d 'Show account status and inference signals'
complete -c ghx -n '__fish_use_subcommand' -a 'init' -d 'Interactive setup wizard'

# ghx-specific flags
complete -c ghx -l gh-user -d 'Force a specific account' -x -a '(
    set -l config_file "$HOME/.config/ghx/config.yml"
    if test -f "$config_file"
        awk \'/^accounts:/{found=1; next} found && /^  [a-zA-Z]/{print $1} found && /^[a-zA-Z]/{exit}\' "$config_file" | tr -d ":"
    end
)'
complete -c ghx -l gh-no-auto -d 'Skip automatic account detection'
complete -c ghx -l gh-debug -d 'Print debug info'
complete -c ghx -l gh-config -d 'Override config file location' -r -F
complete -c ghx -s h -l help -d 'Show help'

# Pass through gh completions for subcommands
complete -c ghx -n 'not __fish_use_subcommand' -w gh
