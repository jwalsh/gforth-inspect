\ .rs two words deep; each return address should be named word+offset
: inner ( -- ) .rs ;
: outer ( -- ) 7 >r inner r> drop ;
outer
depth . fdepth . cr
