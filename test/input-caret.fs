\ input-caret.fs -- .input: file:line, >in, the line, a caret under >in
.input
1 2 + drop    .input
	.input
1 2	.input 2drop
s" 3 .input drop" evaluate
