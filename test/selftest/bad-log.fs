\ bad-log.fs -- a stacks.jsonl line that breaks the schema must fail the run
s" bad.jsonl" out-path w/o create-file throw
>r s\" {\"v\":1,\"event\":\"hello\",\"t\":1}" r@ write-line throw r> close-file throw
