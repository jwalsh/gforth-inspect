\ 10-input-escapes: input.text is the source line, escaped per RFC 8259.
\ The second line holds a double quote, backslashes, a tab and the control
\ bytes 0x01, 0x1b and 0x7f after the comment marker.
log-on
1	2 .stacks \ say "hi" \\ C:\path  end
bye
