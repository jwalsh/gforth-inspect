\ cs-if.fs -- .cs on if / else / then
: t ( f -- ) [ .cs ] if [ .cs ] 1 else [ .cs ] 2 then [ .cs ] drop ;
true t  false t
