\ cs-guard.fs -- regression: .cs outside a definition, with fewer than 3
\ cells or a stray small number on the stack, read below the stack bottom
.cs
3 .cs drop
1 3 .cs 2drop
depth 0 s" clean" assert=
