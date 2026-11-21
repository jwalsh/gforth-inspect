#!/bin/sh
# privacy-scan.sh [path...] -- fail if tracked files (or the given paths)
# hold machine paths, e-mail addresses or tokens.  The repo is public.
#
# Calibrated: scripts/privacy-scan.sh --calibrate plants each pattern in a
# temp file and checks the scan goes red on every one.
set -u

patterns='/Users/[A-Za-z]|/home/[a-z]|/var/folders/|/private/tmp/|/opt/homebrew/Cellar/|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.(com|net|org|sh|io|edu)|gh[pousr]_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9-]{10,}|gist\.github\.com/[A-Za-z0-9-]+/[0-9a-f]{20,}'
# allowed: licence boilerplate and the attribution trailer address
allow='noreply@anthropic\.com|fsf\.org|gnu\.org|scan:allow'

scan() {
    grep -n -I -E "$patterns" "$@" 2>/dev/null | grep -v -E "$allow"
}

if [ "${1:-}" = "--calibrate" ]; then
    tmp=$(mktemp -d)
    fail=0
    for planted in '/Users/someone/x.fs' '/home/someone/x' '/var/folders/9z/T/x' \
                   'someone@example.com' 'ghp_abcdefghijklmnopqrstuvwxyz0123' \
                   'https://gist.github.com/someone/0123456789abcdef0123456789abcdef'; do
        printf '%s\n' "$planted" > "$tmp/planted.txt"
        if scan "$tmp/planted.txt" >/dev/null; then echo "red as expected: $planted"
        else echo "MISSED: $planted"; fail=1; fi
    done
    printf 'clean line\n' > "$tmp/planted.txt"
    if scan "$tmp/planted.txt" >/dev/null; then echo "false positive on a clean file"; fail=1; fi
    rm -rf "$tmp"
    exit $fail
fi

if [ $# -eq 0 ]; then
    cd "$(git rev-parse --show-toplevel)" || exit 2
    set -- $(git ls-files | grep -v -E '^(LICENSE|scripts/privacy-scan.sh)$')
fi
hits=$(scan "$@")
if [ -n "$hits" ]; then
    printf '%s\n' "$hits"
    echo "privacy-scan: private data found (see above)" >&2
    exit 1
fi
echo "privacy-scan: clean ($# files)"
