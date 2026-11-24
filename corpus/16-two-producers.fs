\ 16-two-producers: BEST-EFFORT CONTRACT.  Two gforth processes write one
\ log.  The contract is written for one producer per log (issue #17); this
\ recording shows what the producer does, not what it promises: paced like
\ this, every record lands whole and in order (the fix for #17).
\
\ This file is not loaded.  corpus/record.py starts two gforths with
\ inspect.fs, both logging to one directory, and sends each "pN:" line
\ below to producer N on stdin, waiting until that line has finished
\ before it sends the next (the pacing of experiment 005).  So the
\ interleaving is fixed, and input.file is "" (stdin).
\
\ p0: log-on
\ p1: log-on
\ p0: s" p0" log-id 100 1 .stacks clearstack
\ p1: s" p1" log-id 200 1 .stacks clearstack
\ p0: 100 2 .stacks clearstack
\ p1: 200 2 .stacks clearstack
\ p0: log-off bye
\ p1: log-off bye
