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

# The release assets (docs/RELEASING.org's table, decision 29), copied flat
# into dist/ beside SHA256SUMS. Their basenames must be distinct.
RELEASE_FILES := env/inspect.fs $(SCHEMA) contract/stacks-log.org contract/CONSUMERS.org \
                 contract/CONSUMER-AGENTS.md contract/skill/SKILL.md contract/WORDS.org
ASSET_NAMES   := $(notdir $(RELEASE_FILES))
DIST_FILES    := $(addprefix dist/,$(ASSET_NAMES))

.PHONY: help deps test test-contract test-selftest test-goldens test-one goldens \
        stress test-lldb verify gate release-check clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_.-]+:.*?## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# One probe per tool. A probe RUNS the tool, and the verdict is its exit
# status ("command not found" is output too). Each probe is one quoted word.
DEP_PROBES := "gforth --version" "gforth-fast --version" "gforth-itc --version" \
              "gforth -e 's\" fpick\" find-name 0= throw bye'" \
              "uv --version" "jq --version" "git --version" \
              "python3 --version" "perl -v" "shasum -a 256 /dev/null"
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
	@test -n "$(wildcard $(CORPUS))" || { echo 'stress: CORPUS matches no file: $(CORPUS)'; exit 2; }
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

# pbt/ reads this checkout's inspect.fs by default (pbt/gforth_run.py);
# verify names it explicitly, as CI does; the calibrate scripts that plant a
# fault with `git show REF:env/inspect.fs` use this commit.
PBT_ENV := INSPECT_FS=$(CURDIR)/env/inspect.fs SCHEMA_JSON=$(CURDIR)/$(SCHEMA) INSPECT_REF=HEAD

# Every gate, in order; each has been seen red on a planted fault.
GATES := verify
gate: ## Every gate, in order (the standard alias for verify)
	@for target in $(GATES); do $(MAKE) --no-print-directory $$target || exit 1; done
	@echo "gate: all green"

# release files must not name a machine, a person or the course that uses them
LEAK := /Users/|/home/|/opt/homebrew|/private/|/var/folders|course-repo|course-mode|[a-z0-9._-]+@[a-z0-9-]+\.[a-z]+

release-check: verify ## verify + release hygiene + the 8 assets in dist/
	@echo "== release hygiene: env/ contract/ ($(RELEASE_FILES))"
	@last=$$(git describe --tags --abbrev=0 --match 'v[0-9]*' 2>/dev/null || true); \
	  if [ -z "$$last" ] && [ -n "$$(git tag -l 'v[0-9]*')" ]; then \
	    echo "release-check: version tags exist but none is reachable from HEAD (shallow clone?): fetch tags first (#44)"; exit 1; \
	  fi; \
	  if [ -n "$$last" ]; then \
	    v=$$(sed -n 's/^\\ gforth-inspect v//p' env/inspect.fs); \
	    lastv=$$(git show "$$last:env/inspect.fs" | sed -n 's/^\\ gforth-inspect v//p'); \
	    old=$$(git rev-parse -q --verify "$$last:env/inspect.fs" || true); \
	    new=$$(git hash-object env/inspect.fs); \
	    if [ "$$old" != "$$new" ] && [ "$$v" = "$$lastv" ]; then \
	      echo "release-check: env/inspect.fs changed since $$last but is still v$$v: bump the version (#44)"; exit 1; \
	    fi; \
	    if [ "$$v" != "$$lastv" ] && [ "$$(printf '%s\n%s\n' "$$lastv" "$$v" | sort -V | tail -1)" != "$$v" ]; then \
	      echo "release-check: v$$v is older than $$last (#44)"; exit 1; \
	    fi; \
	  fi
	@test $(words $(sort $(ASSET_NAMES))) = $(words $(RELEASE_FILES)) || \
	  { echo "release-check: two RELEASE_FILES share a basename"; exit 1; }
	@if grep -rn -i -E '$(LEAK)' env contract; then \
	  echo "release-check: machine, personal or course strings above"; exit 1; fi
	@grep -q '^\\ gforth-inspect v[0-9]*\.[0-9]*\.[0-9]*$$' env/inspect.fs
	@v=$$(sed -n 's/^\\ gforth-inspect v//p' env/inspect.fs); \
	  grep -q "s\" $$v\" ;" env/inspect.fs || { echo "inspect-version != header v$$v"; exit 1; }
	@test -f LICENSE || { echo "release-check: no LICENSE"; exit 1; }
	mkdir -p dist && cp $(RELEASE_FILES) dist/
	@stale=$$(ls dist | grep -vxF -e SHA256SUMS $(addprefix -e ,$(ASSET_NAMES)) || true); \
	  test -z "$$stale" || { echo "release-check: dist/ holds files not in RELEASE_FILES: $$stale (gmake clean)"; exit 1; }
	bash scripts/dist-links.sh --calibrate
	@v=$$(sed -n 's/^\\ gforth-inspect v//p' env/inspect.fs); \
	  if tag=$$(git rev-parse -q --verify "refs/tags/v$$v^{commit}"); then \
	    [ "$$tag" = "$$(git rev-parse HEAD)" ] || { echo "release-check: tag v$$v exists and is not HEAD: bump the version"; exit 1; }; \
	  fi; \
	  bash scripts/dist-links.sh dist v$$v $(RELEASE_FILES)
	cd dist && shasum -a 256 $(ASSET_NAMES) > SHA256SUMS
	@test "$$(ls dist | wc -l | tr -d ' ')" = $$(( $(words $(ASSET_NAMES)) + 1 )) || \
	  { echo "release-check: dist/ is not exactly the assets plus SHA256SUMS:"; ls dist; exit 1; }
	scripts/privacy-scan.sh $(DIST_FILES) dist/SHA256SUMS
	@if grep -n -i -E '$(LEAK)' $(DIST_FILES) dist/SHA256SUMS; then \
	  echo "release-check: machine, personal or course strings in dist/ above"; exit 1; fi
	@n=$$(cat $(DIST_FILES) dist/SHA256SUMS | grep -c course-repo || true); \
	  test "$$n" = 0 || { echo "release-check: course-repo in assets"; exit 1; }
	@ls dist
	@cat dist/SHA256SUMS
	@echo "release-check: dist/ ready; tagging and publishing are the owner's call"

# Only git-ignored files under dist/; test scratch is a mktemp dir that
# test/run.sh removes itself.
clean: ## Remove the git-ignored files under dist/
	git clean -fdX -- dist/
