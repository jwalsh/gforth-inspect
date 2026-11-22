# gforth-inspect -- GNU make (gmake on BSD/macOS)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Follows the house standard Makefile; `gmake help` lists the targets.
# The recordings are test/expected/ (the goldens): `goldens` records them,
# `test-goldens` re-runs in a scratch dir and diffs, `gate` runs verify.

SHELL   := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := test
# A recipe that fails must not leave a half-written target behind.
.DELETE_ON_ERROR:

ENGINES ?= gforth gforth-fast gforth-itc
SCHEMA  := contract/stacks-log.schema.json
# jsonschema when uv can provide it, else the built-in subset validator
ifeq ($(origin VALIDATE),undefined)
VALIDATE := $(shell uv run -q --with jsonschema python3 -c 'import jsonschema' \
              >/dev/null 2>&1 && echo 'uv run -q --with jsonschema python3' || echo python3)
endif
export VALIDATE

CONTRACT := $(shell python3 -c 'import json; print(json.load(open("$(SCHEMA)"))["x-contract"])')
export CONTRACT

# canvas.fs is a test bed on harden only and never ships (RELEASING.org)
RELEASE_FILES := env/inspect.fs $(SCHEMA) contract/stacks-log.org CONSUMERS.org
DIST_FILES    := dist/inspect.fs dist/stacks-log.schema.json dist/stacks-log.org dist/CONSUMERS.org

.PHONY: help deps test test-contract test-selftest test-goldens test-one goldens \
        stress test-lldb verify gate release-check clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_.-]+:.*?## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# One probe per tool. A probe RUNS the tool, and the verdict is its exit
# status ("command not found" is output too). Each probe is one quoted word.
DEP_PROBES := "gforth --version" "gforth-fast --version" "gforth-itc --version" \
              "gforth -e 's\" fpick\" find-name 0= throw bye'" \
              "uv --version" "jq --version" "git --version" \
              "python3 --version" "perl -v" "shasum -a 256 /dev/null" "timeout 5 true"
deps: ## Run every tool and print what it answered; a missing one fails
	@for probe in $(DEP_PROBES); do \
	  if output=$$(eval "$$probe" 2>&1 </dev/null); then \
	    answer=$$(printf '%s\n' "$$output" | grep -v '^$$' | head -1 || true); \
	    printf '  ok       %-44s %s\n' "$$probe" "$${answer:-(exit 0)}"; \
	  else printf '  MISSING  %-44s %s\n' "$$probe" "$$(printf '%s\n' "$$output" | head -1 || true)"; missing=1; fi; \
	done; exit $${missing:-0}

test: test-contract test-selftest test-goldens ## Goldens in every engine + schema validation + selftests

test-contract: ## Good records validate, bad ones are rejected; the consumer rule
	@echo "== contract: good records validate, bad ones are rejected ($(VALIDATE))"
	$(VALIDATE) test/validate.py $(SCHEMA) test/contract/good.jsonl
	$(VALIDATE) test/validate.py --expect-invalid $(SCHEMA) test/contract/bad.jsonl
	@echo "== consumer rule: newest hello must announce contract $(CONTRACT)"
	$(VALIDATE) test/validate.py $(SCHEMA) test/contract/streams/*.jsonl
	@for s in test/contract/streams/ok-*.jsonl; do python3 test/consumer.py $(CONTRACT) $$s; done
	@for s in test/contract/streams/bad-*.jsonl; do \
	  python3 test/consumer.py --expect-refused $(CONTRACT) $$s; done
	@grep -q 's" $(CONTRACT)" ;' env/inspect.fs || \
	  { echo "contract-version in inspect.fs != schema x-contract $(CONTRACT)"; exit 1; }

test-selftest: ## The runner goes red on planted failures
	@echo "== runner selftest: failures must fail"
	test/selftest.sh

test-goldens: ## Re-run test/*.fs in a scratch dir and diff against test/expected/
	@echo "== goldens: $(ENGINES)"
	test/run.sh -e "$(ENGINES)"

test-one: ## One test, every engine: gmake test-one T=test/x.fs
	test/run.sh -e "$(ENGINES)" $(T)

goldens: ## Record test/expected/ afresh (review the diff); refuses one naming the home dir
	@case "$(HOME)" in ""|/) echo "goldens: HOME is '$(HOME)', so test/expected/ cannot be checked for it"; exit 1;; esac
	test/run.sh -u -e "$(ENGINES)"
	@if grep -rlF "$(HOME)" test/expected >/dev/null 2>&1; then \
	  echo "goldens: test/expected/ contains the home directory:"; grep -rlF "$(HOME)" test/expected; \
	  echo "goldens: refused; restore with git checkout -- test/expected"; exit 1; fi
	git status --short test/expected

stress: ## Load real programs with and without inspect.fs: CORPUS="dir/*.fs ..."
	@test -n "$(CORPUS)" || { echo 'usage: gmake stress CORPUS="dir/*.fs ..."'; exit 2; }
	test/stress.sh $(wildcard $(CORPUS))

test-lldb: ## lldb/check.sh; skipped where debugserver cannot attach
	@if /usr/bin/lldb -b -o run -- /usr/bin/true >/dev/null 2>&1; then \
	  lldb/check.sh; \
	else echo "SKIP test-lldb: debugserver cannot launch here (sandbox?)"; fi

verify: ## The CONTRIBUTING.org baseline: privacy, guides, test, pbt check + calibrate
	scripts/privacy-scan.sh --calibrate
	scripts/privacy-scan.sh
	bash scripts/check-guides.sh --calibrate
	bash scripts/check-guides.sh
	$(MAKE) test
	$(PBT_ENV) $(MAKE) -C pbt check
	$(PBT_ENV) $(MAKE) -C pbt calibrate

# pbt/ would read inspect.fs from the `harden` branch (pbt/gforth_run.py).
# verify points it at this working tree, as CI does; the calibrate scripts
# that plant a fault with `git show REF:env/inspect.fs` use this commit.
PBT_ENV := INSPECT_FS=$(CURDIR)/env/inspect.fs SCHEMA_JSON=$(CURDIR)/$(SCHEMA) INSPECT_REF=HEAD

# Every gate, in order; each has been seen red on a planted fault.
GATES := verify
gate: ## Every gate, in order (the standard alias for verify)
	@for target in $(GATES); do $(MAKE) --no-print-directory $$target || exit 1; done
	@echo "gate: all green"

# release files must not name a machine, a person or the course that uses them
LEAK := /Users/|/home/|/opt/homebrew|/private/|/var/folders|sicpminus|course\.el|[a-z0-9._-]+@[a-z0-9-]+\.[a-z]+

release-check: verify ## verify + release hygiene + dist/ with SHA256SUMS
	@echo "== release hygiene: $(RELEASE_FILES) contract/*"
	@if grep -n -i -E '$(LEAK)' env/*.fs contract/*; then \
	  echo "release-check: machine, personal or course strings above"; exit 1; fi
	@grep -q '^\\ gforth-inspect v[0-9]*\.[0-9]*\.[0-9]*$$' env/inspect.fs
	@v=$$(sed -n 's/^\\ gforth-inspect v//p' env/inspect.fs); \
	  grep -q "s\" $$v\" ;" env/inspect.fs || { echo "inspect-version != header v$$v"; exit 1; }
	@test -f LICENSE || { echo "release-check: no LICENSE"; exit 1; }
	mkdir -p dist && cp $(RELEASE_FILES) dist/
	@stale=$$(ls dist | grep -vxE 'inspect\.fs|stacks-log\.schema\.json|stacks-log\.org|CONSUMERS\.org|SHA256SUMS' || true); \
	  test -z "$$stale" || { echo "release-check: dist/ holds files not in RELEASE_FILES: $$stale (clear dist/ by hand)"; exit 1; }
	bash scripts/dist-links.sh --calibrate
	@v=$$(sed -n 's/^\\ gforth-inspect v//p' env/inspect.fs); \
	  if [ "$${v%%.*}" = 0 ] && [ "$$(echo $$v | cut -d. -f2)" -lt 5 ]; then \
	    ref=$$(git rev-parse HEAD); echo "release-check: dry run: v$$v is untagged (no tags before v0.5.0); links pin to $$ref"; \
	  else ref=v$$v; fi; \
	  bash scripts/dist-links.sh dist $$ref
	cd dist && shasum -a 256 inspect.fs stacks-log.schema.json stacks-log.org CONSUMERS.org > SHA256SUMS
	scripts/privacy-scan.sh $(DIST_FILES) dist/SHA256SUMS
	@n=$$(cat $(DIST_FILES) | grep -c sicpminus || true); \
	  test "$$n" = 0 || { echo "release-check: sicpminus in assets"; exit 1; }
	@cat dist/SHA256SUMS
	@echo "release-check: dist/ ready; tagging (v0.5.0 and later only) and publishing are the owner's call"

# Only git-ignored files under dist/; test scratch is a mktemp dir that
# test/run.sh removes itself.
clean: ## Remove the git-ignored files under dist/
	git clean -fdX -- dist/
