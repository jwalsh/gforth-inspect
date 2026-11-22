\ ~~~ in a nested word: file:line, word, all stacks to stderr
: inner ( n -- n ) 2* ~~~ ;
: outer ( -- n ) 2.5e 5 inner ;
outer . fdrop cr
depth . fdepth . cr
