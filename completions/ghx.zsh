#compdef ghx

# Zsh completion for ghx — Intelligent GitHub CLI account switcher

_ghx() {
    local -a ghx_flags ghx_commands

    ghx_flags=(
        '--gh-user[Force a specific account]:account label:->accounts'
        '--gh-no-auto[Skip automatic account detection]'
        '--gh-debug[Print debug info]'
        '--gh-config[Override config file location]:config file:_files'
        '--help[Show help]'
        '-h[Show help]'
    )

    ghx_commands=(
        'status:Show account status and inference signals'
        'init:Interactive setup wizard'
    )

    # If first arg position, offer ghx commands + gh subcommands
    if (( CURRENT == 2 )); then
        _describe -t commands 'ghx commands' ghx_commands
        # Also complete gh subcommands
        _arguments -C $ghx_flags '*::gh args:->gh_passthrough'
    else
        # Pass through to gh completions
        _arguments -C $ghx_flags '*::gh args:->gh_passthrough'
    fi

    case "$state" in
        accounts)
            # Read account labels from config
            local config_file="${HOME}/.config/ghx/config.yml"
            if [[ -f "$config_file" ]]; then
                local -a labels
                labels=(${(f)"$(grep -E '^\s+\w+:' "$config_file" | head -20 | sed 's/:.*//' | tr -d ' ')"})
                _describe 'account' labels
            fi
            ;;
        gh_passthrough)
            # Delegate to gh's own completions if available
            if (( $+functions[_gh] )); then
                _gh
            fi
            ;;
    esac
}

_ghx "$@"
