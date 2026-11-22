\ log-producer-b.fs -- the second producer for test/log-two-producers.fs:
\ one hello and one snapshot (id B1), appended to the shared log
log-on s" B1" log-id 9 .stacks drop log-off
