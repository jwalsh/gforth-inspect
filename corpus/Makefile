# corpus/ -- recorded stacks.jsonl logs for consumer authors.  gmake -C corpus help
# Standard shape (project-makefile): every claim is a recorded run, check re-runs
# and diffs, gate runs every check in order.  GNU make: use gmake on macOS.
SHELL := /bin/sh
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:

PYTHON ?= python3
ENGINE ?= gforth
# the repository root: record.py reads pbt/gforth_run.py and pbt/consumers/ there
REPO ?= ..
RECORD := $(PYTHON) record.py --repo $(REPO)
# what a recording must never contain: the home directory or a temp path
# ([f]olders: the bracket keeps scripts/privacy-scan.sh from flagging this line)
PRIVATE_FIXED := $(HOME) $(patsubst %/,%,$(TMPDIR))
PRIVATE_PATTERN := /Users/|/home/|/var/[f]olders/|/private/|/tmp/

.PHONY: help deps record check engines calibrate gate clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_.-]+:.*?## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

DEP_PROBES := "gforth --version" "gforth-fast --version" "gforth-itc --version" \
              "jq --version" "$(PYTHON) --version" "git --version"
deps: ## Run every tool and print what it answered; a missing one fails
	@for probe in $(DEP_PROBES); do \
	  if output=$$($$probe 2>&1); then answer=$$(printf '%s\n' "$$output" | grep -v '^$$' | head -1); \
	    printf '  ok       %-24s %s\n' "$$probe" "$$answer"; \
	  else printf '  MISSING  %-24s %s\n' "$$probe" "$$(printf '%s\n' "$$output" | head -1)"; missing=1; fi; done; \
	exit $${missing:-0}

# scan DIR TARGET: fail, naming the files, if any recording holds a private path
define scan_private
	@leaks=$$( { for fixed in $(PRIVATE_FIXED); do grep -rlF "$$fixed" $(1); done; \
	             grep -rlE '$(PRIVATE_PATTERN)' $(1); } 2>/dev/null | sort -u ); \
	if [ -n "$$leaks" ]; then \
	  echo "$(2): REFUSED, a recording holds the home directory or a temp path:"; \
	  printf '  %s\n' $$leaks; rm -rf $(1); exit 1; fi
endef

record: ## Re-record every .jsonl, .expect.json and PROVENANCE; read the diff before committing
	@rm -rf .record
	@$(RECORD) --engine $(ENGINE) .record
	$(call scan_private,.record,record)
	@rm -f ./*.jsonl ./*.expect.json && cp .record/* . && rm -rf .record && echo "record: written; review with git diff"

check: ## A fresh recording equals the committed one, file for file
	@rm -rf .check
	@$(RECORD) --engine $(ENGINE) .check
	$(call scan_private,.check,check)
	@status=0; \
	for fresh in .check/*; do name=$${fresh#.check/}; \
	  if [ ! -f "$$name" ]; then echo "check: DIFFERS: $$name is not committed"; status=1; \
	  elif ! diff -u "$$name" "$$fresh"; then echo "check: DIFFERS: $$name"; status=1; fi; done; \
	for committed in *.jsonl *.expect.json; do \
	  [ -f ".check/$$committed" ] || { echo "check: DIFFERS: $$committed has no scenario"; status=1; }; done; \
	if [ $$status -eq 0 ]; then echo "check: the recordings reproduce"; rm -rf .check; \
	else echo "check: fresh run left in corpus/.check/"; fi; exit $$status

engines: ## gforth-fast and gforth-itc record the same logs as gforth
	@status=0; for engine in gforth-fast gforth-itc; do \
	  rm -rf .engine-$$engine; \
	  $(RECORD) --engine $$engine .engine-$$engine >/dev/null || exit 1; \
	  engine_status=0; \
	  for fresh in .engine-$$engine/*.jsonl .engine-$$engine/*.expect.json; do \
	    name=$${fresh#.engine-$$engine/}; \
	    diff -u "$$name" "$$fresh" || { echo "engines: $$engine DIFFERS: $$name"; engine_status=1; }; done; \
	  if [ $$engine_status -eq 0 ]; then echo "engines: $$engine records the same logs"; rm -rf .engine-$$engine; \
	  else echo "engines: $$engine run left in corpus/.engine-$$engine/"; status=1; fi; \
	done; exit $$status

calibrate: ## Planted faults: check must go red on a changed field, record on a private path
	@MAKE="$(MAKE)" sh calibrate.sh

GATES := check engines calibrate
gate: ## Every gate, in order
	@for target in $(GATES); do $(MAKE) --no-print-directory $$target || exit 1; done
	@echo "gate: all green"

clean: ## Remove scratch output
	rm -rf .record .check .engine-gforth-fast .engine-gforth-itc
