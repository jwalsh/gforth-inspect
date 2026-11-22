\ 11-utf8: multi-byte UTF-8 passes through; a byte that is not valid UTF-8
\ (0xff here) becomes U+FFFD.  This file is deliberately not valid UTF-8.
log-on
.stacks \ λ → ∀ 日本 🙂 bad:� end
bye
