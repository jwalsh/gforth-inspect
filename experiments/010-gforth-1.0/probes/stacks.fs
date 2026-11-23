\ .stacks inside a colon word: data, float, return (one caller), input
: inner ( -- ) .stacks ;
: outer ( -- ) inner ;
1 -2 3 1.5e -0.25e outer
depth . fdepth . cr
