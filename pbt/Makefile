# pbt/ -- property tests over env/inspect.fs.  gmake -C pbt check
# inspect.fs and the schema come from INSPECT_REF (default: harden); see gforth_run.py.

UV_RUN := uv run --no-project --with hypothesis --with jsonschema --with pytest
PROFILE ?= default
TESTS := $(wildcard test_*.py)

.PHONY: check smoke calibrate

smoke:
	$(UV_RUN) python gforth_run.py

check: smoke
ifeq ($(TESTS),)
	@echo "no test_*.py yet"
else
	$(UV_RUN) pytest -q --hypothesis-profile=$(PROFILE) $(TESTS)
endif

# every experiment adds its planted-fault run here; check must go red on each
calibrate:
	@ls calibrate/*.sh >/dev/null 2>&1 || { echo "no calibration yet"; exit 0; }
	@for script in calibrate/*.sh; do echo "== $$script"; sh $$script || exit 1; done
