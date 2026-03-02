# Bash completion for ghx — Intelligent GitHub CLI account switcher

_ghx_completions() {
    local cur prev
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # ghx-specific flags
    local ghx_flags="--gh-user --gh-no-auto --gh-debug --gh-config --help -h"
    local ghx_commands="status init"

    case "$prev" in
        --gh-user)
            # Complete with account labels from config
            local config_file="${HOME}/.config/ghx/config.yml"
            if [[ -f "$config_file" ]]; then
                local labels
                labels=$(awk '/^accounts:/{found=1; next} found && /^  [a-zA-Z]/{print $1} found && /^[a-zA-Z]/{exit}' "$config_file" | tr -d ':')
                COMPREPLY=($(compgen -W "$labels" -- "$cur"))
            fi
            return
            ;;
        --gh-config)
            COMPREPLY=($(compgen -f -- "$cur"))
            return
            ;;
    esac

    # First argument: offer ghx commands and flags
    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=($(compgen -W "$ghx_commands $ghx_flags" -- "$cur"))
        # Also try gh completions
        if type _gh_completions &>/dev/null; then
            _gh_completions
        fi
        return
    fi

    # Otherwise delegate to gh completions if available
    if type _gh_completions &>/dev/null; then
        _gh_completions
    fi
}

complete -F _ghx_completions ghx
