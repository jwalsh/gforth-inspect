\ load: after inspect.fs, which public words are defined (-1) or not (0)
: defined? ( c-addr u -- ) 2dup type space find-name 0<> . cr ;
s" .stacks" defined?  s" .rs" defined?  s" .input" defined?
s" .cs" defined?  s" ~~~" defined?  s" all-~~" defined?
s" dbg-fix" defined?  s" dbg+" defined?  s" log-on" defined?
s" log-off" defined?  s" log-where" defined?  s" log-id" defined?
s" fclearstack" defined?  s" inspect-version" defined?
s" rs-full" defined?  s" contract-version" defined?
depth . fdepth . cr
