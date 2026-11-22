\ base-kept.fs -- regression: .rs did `hex. decimal' and left BASE at 10.
\ Nothing may change BASE; offsets and depths print in decimal, the log is
\ always decimal (JSON has no hex).
: w ( -- ) .stacks ;
: w2 ( -- ) w ;
: kk ( -- ) ~~~ ;
log-on
hex 1F w2 kk .rs  log-off
base @ decimal 16 s" BASE still hex" assert=
$1F s" value" assert=
: cs ( -- ) [ hex ] 1 if [ .cs ] then [ base @ decimal 16 s" .cs keeps BASE" assert= ] ;
