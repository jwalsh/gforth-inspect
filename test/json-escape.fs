\ json-escape.fs -- input text with " \ tab, control characters, DEL,
\ valid UTF-8 and invalid bytes: every line must still be valid JSON
\ (the text sits in a comment, so the parser never sees it as words)
log-on
s" .stacks" evaluate  s\" .stacks \\ \"quoted\" back\\\\slash" evaluate
s\" .stacks \\ \t tab \x01 \x1f \x7f del \r cr \b bs \f ff" evaluate
s\" .stacks \\ \xce\xbb lambda \xe2\x86\x92 arrow \xf0\x9f\x98\x80 emoji" evaluate
s\" .stacks \\ \xff \xc0\xaf \xed\xa0\x80 \xe0\x80\x80 \xf4\x90\x80\x80 \xce" evaluate
	.stacks	\ a real tab in the file
log-off
