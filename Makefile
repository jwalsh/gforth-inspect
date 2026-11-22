# gforth-inspect -- GNU make (gmake on BSD/macOS)
#
#   gmake test           goldens in every engine + schema validation + selftests
#   gmake test-one T=test/x.fs   one test, every engine
#   gmake goldens        regenerate test/expected/ (review the diff!)
#   gmake stress CORPUS="dir/*.fs ..."   load real programs with/without inspect.fs
#   gmake test-lldb      lldb/check.sh; skipped where debugserver cannot attach
#   gmake verify         the CONTRIBUTING.org baseline
#   gmake release-check  verify + release hygiene + dist/ with SHA256SUMS

SHELL   := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := test

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

.PHONY: test test-contract test-selftest test-goldens test-one goldens \
        stress test-lldb verify release-check

test: test-contract test-selftest test-goldens

test-contract:
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

test-selftest:
	@echo "== runner selftest: failures must fail"
	test/selftest.sh

test-goldens:
	@echo "== goldens: $(ENGINES)"
	test/run.sh -e "$(ENGINES)"

test-one:
	test/run.sh -e "$(ENGINES)" $(T)

goldens:
	test/run.sh -u -e "$(ENGINES)"
	git status --short test/expected

stress:
	@test -n "$(CORPUS)" || { echo 'usage: gmake stress CORPUS="dir/*.fs ..."'; exit 2; }
	test/stress.sh $(wildcard $(CORPUS))

test-lldb:
	@if /usr/bin/lldb -b -o run -- /usr/bin/true >/dev/null 2>&1; then \
	  lldb/check.sh; \
	else echo "SKIP test-lldb: debugserver cannot launch here (sandbox?)"; fi

verify:
	scripts/privacy-scan.sh --calibrate
	scripts/privacy-scan.sh
	bash scripts/check-guides.sh --calibrate
	bash scripts/check-guides.sh
	$(MAKE) test
	$(MAKE) -C pbt check
	$(MAKE) -C pbt calibrate

# release files must not name a machine, a person or the course that uses them
LEAK := /Users/|/home/|/opt/homebrew|/private/|/var/folders|sicpminus|course\.el|[a-z0-9._-]+@[a-z0-9-]+\.[a-z]+

release-check: verify
	@echo "== release hygiene: $(RELEASE_FILES) contract/*"
	@if grep -n -i -E '$(LEAK)' env/*.fs contract/*; then \
	  echo "release-check: machine, personal or course strings above"; exit 1; fi
	@grep -q '^\\ gforth-inspect v[0-9]*\.[0-9]*\.[0-9]*$$' env/inspect.fs
	@v=$$(sed -n 's/^\\ gforth-inspect v//p' env/inspect.fs); \
	  grep -q "s\" $$v\" ;" env/inspect.fs || { echo "inspect-version != header v$$v"; exit 1; }
	@test -f LICENSE || { echo "release-check: no LICENSE"; exit 1; }
	mkdir -p dist && cp $(RELEASE_FILES) dist/
	bash scripts/dist-links.sh --calibrate
	@v=$$(sed -n 's/^\\ gforth-inspect v//p' env/inspect.fs); bash scripts/dist-links.sh dist $$v
	cd dist && shasum -a 256 inspect.fs stacks-log.schema.json stacks-log.org CONSUMERS.org > SHA256SUMS
	scripts/privacy-scan.sh $(DIST_FILES) dist/SHA256SUMS
	@n=$$(cat $(DIST_FILES) | grep -c sicpminus || true); \
	  test "$$n" = 0 || { echo "release-check: sicpminus in assets"; exit 1; }
	@cat dist/SHA256SUMS
	@echo "release-check: dist/ ready; tagging and publishing are the owner's call"
