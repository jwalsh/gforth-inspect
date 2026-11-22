#!/bin/sh
# 007 plant (a): the twin's strict reader replaced with cheshire's default
# parse-string, which takes raw control characters and the first of {..}{..}.
# Its numbers are brought to the twin's types (cheshire gives Integer and
# BigInt), so the plant differs from the twin in leniency only.
. "$(dirname "$0")/007.lib"
cat > "$tmp/plant.clj" <<'PLANT'
(require '[cheshire.core :as cheshire] '[clojure.walk :as walk])
(defn read-json [text _allow-constants]
  (try (walk/postwalk (fn [x] (cond (map? x) (apply dict (mapcat identity x))
                                    (instance? Integer x) (long x)
                                    (instance? clojure.lang.BigInt x) (biginteger x)
                                    :else x))
                      (cheshire/parse-string text))
       (catch Exception error (bad-json (str error)))))
PLANT
plant_redefine "$tmp/plant.clj"
expect_red generated 'disagree checker: mutation (raw-control|trailing-object)[^:]*'
