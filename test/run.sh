#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# test/run.sh -- run test/*.fs in each engine, diff against test/expected/,
# validate every stacks.jsonl line against contract/stacks-log.schema.json.
#
#   test/run.sh [-u] [-e "gforth gforth-fast gforth-itc"] [test/x.fs ...]
#     -u  update goldens (refuses to bless an ASSERT FAIL or a schema error)
#   VALIDATE  command prefix for test/validate.py (default: python3)
#
# Header directives in a test file (lines starting "\ test: "):
#   \ test: skip <reason>       not run
#   \ test: stdin <printf fmt>  keys piped to gforth (dbg)
#   \ test: noinspect           do not load env/inspect.fs
#   \ test: load <file>         also load <file> (after inspect.fs)
#   \ test: env NAME=VALUE      set a variable; $TMP is the test's temp dir
#   \ test: unset NAME          remove a variable (HOME is always $TMP/home)
#   \ test: exit N              expected exit status (default 0)
# Every test also sees TEST_ENGINE (the engine running it, for a test that
# starts a second gforth) and TEST_OUT (a dir for files it writes).
#
# Golden: test/expected/<name>.out, or <name>@<engine>.out when an engine
# really differs.  It holds masked stdout, stderr, every *.jsonl and every
# file under $TEST_OUT, and the exit status.
set -u
cd "$(dirname "$0")/.."
ROOT=$PWD
ENGINES="gforth gforth-fast gforth-itc"
UPDATE=0
VALIDATE=${VALIDATE:-python3}
while getopts "ue:" opt; do
  case $opt in
    u) UPDATE=1 ;;
    e) ENGINES=$OPTARG ;;
    *) exit 2 ;;
  esac
done
shift $((OPTIND - 1))
if [ $# -gt 0 ]; then TESTS=("$@"); else TESTS=(test/*.fs); fi
SCHEMA=contract/stacks-log.schema.json
EXPECTED=${EXPECTED:-test/expected}
CONTRACT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["x-contract"])' "$SCHEMA")
WORK=$(mktemp -d "${TMPDIR:-/tmp}"/gforth-inspect-test.XXXXXX); WORK=${WORK//\/\//\/}
trap 'rm -rf "$WORK"' EXIT

directive() { sed -n "s/^\\\\ test: $2 *//p" "$1"; }

pass=0 fail=0 skip=0
bump() { local v=$1_${2//-/_}; eval "$v=\$(( \${$v:-0} + 1 ))"; }
count() { local v=$1_${2//-/_}; eval "echo \${$v:-0}"; }
failed=()

run_one() { # engine test -> writes $tmp/actual, returns 0 if output usable
  local e=$1 t=$2 name keys
  name=$(basename "$t" .fs)
  tmp=$WORK/$e-$name
  mkdir -p "$tmp/home" "$tmp/state" "$tmp/out"
  local -a cmd=("$e")
  [ -z "$(directive "$t" noinspect)" ] && cmd+=(env/inspect.fs)
  cmd+=(test/lib/assert.fs)
  while read -r f; do [ -n "$f" ] && cmd+=("$f"); done < <(directive "$t" load)
  cmd+=("$t" -e bye)
  local -a envs=(HOME="$tmp/home" XDG_STATE_HOME="$tmp/state" TEST_OUT="$tmp/out" TEST_ENGINE="$e")
  local -a unsets=(-u GFORTH_INSPECT_LOG_DIR)
  while read -r kv; do
    [ -n "$kv" ] && envs+=("${kv//\$TMP/$tmp}")
  done < <(directive "$t" env)
  while read -r u; do
    [ -n "$u" ] && unsets+=(-u "$u") && envs=("${envs[@]/#$u=*/}")
  done < <(directive "$t" unset)
  local -a clean=()
  for kv in "${envs[@]}"; do [ -n "$kv" ] && clean+=("$kv"); done
  keys=$(directive "$t" stdin)
  # shellcheck disable=SC2059
  printf -- "$keys" > "$tmp/stdin"
  env "${unsets[@]}" "${clean[@]}" timeout 10 "${cmd[@]}" \
      < "$tmp/stdin" > "$tmp/stdout" 2> "$tmp/stderr"
  local rc=$?
  {
    echo "## stdout"; MASK_TMP=$tmp perl test/mask.pl "$tmp/stdout"
    echo "## stderr"; MASK_TMP=$tmp perl test/mask.pl "$tmp/stderr"
    while read -r j; do
      echo "## log ${j#"$tmp"/}"; MASK_TMP=$tmp perl test/mask.pl "$j"
    done < <(find "$tmp" -name '*.jsonl' | sort)
    while read -r f; do
      echo "## file ${f#"$tmp"/out/}"; MASK_TMP=$tmp perl test/mask.pl "$f"
    done < <(find "$tmp/out" -type f | sort)
    echo "## exit $rc"
  } > "$tmp/actual"
}

for t in "${TESTS[@]}"; do
  name=$(basename "$t" .fs)
  reason=$(directive "$t" skip)
  if [ -n "$reason" ]; then
    echo "SKIP $name: $reason"; skip=$((skip + 1)); continue
  fi
  for e in $ENGINES; do
    run_one "$e" "$t"
    problems=()
    grep -q "ASSERT FAIL" "$tmp/actual" && problems+=("assertion failed")
    want_rc=$(directive "$t" exit); want_rc=${want_rc:-0}
    grep -qx "## exit $want_rc" "$tmp/actual" || problems+=("exit status $(tail -1 "$tmp/actual" | cut -c9-), want $want_rc")
    grep -q "^redefined " "$tmp/stderr" && problems+=("redefinition warning")
    while read -r j; do
      if ! $VALIDATE test/validate.py "$SCHEMA" "$j" 2> "$tmp/validate"; then
        problems+=("schema: $(grep -v '^validate:' "$tmp/validate" | head -3 | tr '\n' ' ')")
      elif grep -q '"event":"hello"' "$j" && ! python3 test/consumer.py "$CONTRACT" "$j" 2> "$tmp/consumer"; then
        problems+=("consumer: $(cat "$tmp/consumer")")
      fi
    done < <(find "$tmp" -name '*.jsonl' | sort)
    base=$EXPECTED/$name.out
    own=$EXPECTED/$name@$e.out
    if [ $UPDATE = 1 ] && [ ${#problems[@]} = 0 ]; then
      if [ "$e" = gforth ] || [ ! -f "$base" ]; then
        cp "$tmp/actual" "$base"; rm -f "$own"
      elif cmp -s "$tmp/actual" "$base"; then rm -f "$own"
      else cp "$tmp/actual" "$own"; fi
    fi
    golden=$base; [ -f "$own" ] && golden=$own
    if [ ! -f "$golden" ]; then
      problems+=("no golden $golden")
    elif ! cmp -s "$golden" "$tmp/actual"; then
      problems+=("differs from $golden")
    fi
    if [ ${#problems[@]} = 0 ]; then
      pass=$((pass + 1)); bump P "$e"
    else
      fail=$((fail + 1)); bump F "$e"
      failed+=("$e $name")
      echo "FAIL $e $name: ${problems[*]}"
      [ -f "$golden" ] && diff -u "$golden" "$tmp/actual" | head -40
    fi
  done
done
for e in $ENGINES; do
  echo "$e: $(count P "$e") passed, $(count F "$e") failed"
done
echo "total: $pass passed, $fail failed, $skip skipped"
[ $fail = 0 ]
