\ idle.fs -- park inside MS with known stacks so lldb can attach (-p PID)
: deep ( -- ) ( F: -- )  11 22 33  1.5e 2.5e  60000 ms ;
\ test: skip parks 60 s for lldb -p; run by lldb/check.sh
: wrap ( -- )  5 0 do i 3 = if deep then loop ;
wrap
bye
