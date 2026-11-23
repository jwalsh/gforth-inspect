\ 17-evaluated-string: snapshots taken inside evaluate.  input.file is
\ "*evaluated string*", input.line is -1 and input.text is the evaluated
\ string, not the file's line; a word defined in the file and run from
\ evaluate still gets its own where and src.
: ev ( -- ) 9 ~~~ drop ;
log-on
s" 7 .stacks drop" evaluate
s" ev" evaluate
bye
