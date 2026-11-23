\ log-on with ~~~ and all-~~ ~~: where and src are filled
: a ( -- ) 1 ~~~ drop ;
: b ( -- ) 2 ~~ drop ;
log-on all-~~ a b log-off
depth . fdepth . cr
