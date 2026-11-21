# pbt/ -- property tests over env/inspect.fs.  gmake -C pbt check
# inspect.fs and the schema come from INSPECT_REF (default: harden); see gforth_run.py.

UV_RUN := uv run --no-project --with hypothesis --with jsonschema --with pytest
PROFILE ?= default
SEED ?=
SEED_OPT := $(if $(SEED),--hypothesis-seed=$(SEED))
TESTS := $(wildcard test_*.py)

.PHONY: check smoke calibrate

smoke:
	$(UV_RUN) python gforth_run.py

check: smoke
ifeq ($(TESTS),)
	@echo "no test_*.py yet"
else
	$(UV_RUN) pytest -q --hypothesis-profile=$(PROFILE) --hypothesis-show-statistics $(SEED_OPT) $(TESTS)
endif

# Every experiment adds a planted-fault script to CALIBRATE_DIR.  A script
# exits 0 only if the tests went red on its planted fault, so calibrate is
# green exactly when every gate was seen to fail.  The recipe is one shell:
# an `exit` on one recipe line ends only that line, not the target.
CALIBRATE_DIR ?= calibrate

calibrate:
	@set -e; \
	scripts=$$(ls $(CALIBRATE_DIR)/*.sh 2>/dev/null || true); \
	if [ -z "$$scripts" ]; then echo "no calibration yet"; exit 0; fi; \
	for script in $$scripts; do echo "== $$script"; sh "$$script"; done
