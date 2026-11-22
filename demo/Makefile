# demo/ -- try the inspector live, or record it.  gmake -C demo help
# Every run happens in a fresh mktemp -d (see sandbox.sh).

COLS ?= 110
ROWS ?= 34

.PHONY: help tour stop watch record
.DELETE_ON_ERROR:

help: ## Show this help
	@grep -E '^[a-z.-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | expand -t 12

tour: ## Start the detached tmux tour (gforth | log through jq); attach yourself
	@./tour-tmux.sh

stop: ## Remove the tmux tour session
	@tmux kill-session -t =gforth-inspect-tour 2>/dev/null && echo stopped || echo "no tour session"

watch: ## Run the self-driving demo in this terminal
	@./record.sh

record: tour.gif ## Record tour.cast (asciicast v2) and render tour.gif with agg

tour.cast: record.sh tour.fs sandbox.sh cast.py
	@# cast.py, not asciinema rec: asciinema 2.4 crashes on exit when stdin is a pipe
	python3 -I cast.py $@.tmp $(COLS) $(ROWS) -- ./record.sh
	@# the sandbox path is the only machine detail that can appear: name it neutrally
	sed -E -e 's#(/private)?/(var/folders|tmp)/[^"\\ ]*gforth-inspect-demo\.[A-Za-z0-9]+#/demo#g' $@.tmp > $@
	@rm -f $@.tmp
	@../scripts/privacy-scan.sh $@

tour.gif: tour.cast
	@command -v agg >/dev/null || { echo "agg missing: brew install agg"; exit 1; }
	agg --cols $(COLS) --rows $(ROWS) --font-size 14 --speed 1.5 --theme monokai $< $@
