\ .cs at compile time inside IF and BEGIN
: t ( f -- ) IF [ .cs ] BEGIN [ .cs ] -1 UNTIL THEN ;
true t false t
depth . fdepth . cr
