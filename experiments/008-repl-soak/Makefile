# experiments/008-repl-soak -- the REPL soak harness.  gmake, not make.
#
#   gmake calibrate            every check red on its planted fault, then green
#   gmake smoke                1 hour, 10 REPLs, all three engines, in the foreground
#   gmake soak-start           the 20-hour soak, detached, in tmux session $(SESSION)
#   gmake status               the status file
#
# Targets are read from ${XDG_CONFIG_HOME:-~/.config}/gforth-inspect-soak/targets
# (format in soak/config.py); nothing here names one.
UV      := uv run --no-project --with jsonschema python3 -u -m soak
SESSION := gforth-inspect-soak
NAME    ?= soak-$(shell date -u +%Y%m%d)
HOURS   ?= 20
SLOTS   ?= 10

.PHONY: help calibrate smoke soak-start status privacy

help:
	@sed -n 's/^#   //p' Makefile

calibrate:
	$(UV) calibrate

smoke:
	$(UV) run smoke-$(shell date -u +%Y%m%dT%H%M) --hours 1 --slots $(SLOTS)

soak-start:
	@if tmux has-session -t $(SESSION) 2>/dev/null; then echo "tmux session $(SESSION) exists"; exit 1; fi
	tmux new-session -d -s $(SESSION) -e PATH="$$PATH" -c "$(CURDIR)" "./run-soak.sh $(NAME) $(HOURS) --slots $(SLOTS); exec bash"
	@echo "started $(NAME) in tmux session $(SESSION); gmake status"

status:
	@$(UV) status $(if $(RUN),$(RUN))

privacy:
	uv run --no-project python3 privacy_check.py
