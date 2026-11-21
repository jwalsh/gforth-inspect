\ json-src.fs -- regression: "src" (file:line of ~~~) was written without
\ escaping, so a file name with a quote or backslash broke the record
create fname 1024 allot  variable fname#
: put ( c-addr u -- ) dup fname# ! fname swap move ;
s\" we\"ird\\name.fs" out-path put
fname fname# @ w/o create-file throw
>r s" : w ( -- ) ~~~ ; w" r@ write-line throw r> close-file throw
log-on fname fname# @ included log-off
