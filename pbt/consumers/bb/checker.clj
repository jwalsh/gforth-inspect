#!/usr/bin/env bb
;; Reference consumer 2, the bb twin of pbt/consumers/checker.py (experiment 007).
;;
;;     bb checker.clj stacks.jsonl schema.json [--expect 1.1] [--no-version-stop]
;;
;; It does what checker.py does, quirks included, so a consumer cannot
;; tell the two apart (experiments/007-bb-consumers/README.org):
;;
;; 1. Version stop.  Read the newest `hello`.  If its `contract` differs
;;    from the expected MAJOR.MINOR in MAJOR or MINOR, or is missing, stop
;;    and say so.  `--no-version-stop` bypasses this.
;; 2. Read the last line, decode it as strict UTF-8 and strict JSON.
;; 3. Validate it with checker.py's subset of JSON Schema (type, required,
;;    enum, const, items, oneOf, properties, additionalProperties), in its
;;    order, with its messages.  Annotations checker.py ignores are ignored;
;;    any other keyword makes this twin refuse to run (exit 2), where
;;    checker.py would ignore it.
;; 4. Extract data, float, rs, input (file, line, in, text only), where, src.
;;
;; The result is one JSON object on stdout, written as Python's
;; json.dumps(..., ensure_ascii=False) writes it.  Where checker.py raises,
;; this twin exits 1 with the same exception line on stderr.
;;
;; Nothing beyond babashka itself: the JSON reader is hand-written because
;; cheshire's is lenient (raw control characters, `{..}{..}`), and Python's
;; json.loads has rules of its own (NaN, the 4300-digit integer limit).

(ns checker
  (:require [clojure.string :as str])
  (:import (java.math BigDecimal BigInteger MathContext RoundingMode)
           (java.nio ByteBuffer)
           (java.nio.charset CharacterCodingException CodingErrorAction StandardCharsets)
           (java.nio.file Files NoSuchFileException Paths)))

(def expected-contract "1.1")
(def input-keys ["file" "line" "in" "text"])
(def snapshot-keys ["where" "src" "data" "float" "rs" "input"])

;; --- Python's exceptions --------------------------------------------------

(defn- py-raise
  "Raise what checker.py would raise uncaught: class and message."
  [class-name message]
  (throw (ex-info message {::py-exception class-name})))

;; --- Python's dict: insertion order, a repeated key keeps its first place ---
;; babashka has no LinkedHashMap, so an object is a Clojure map whose
;; metadata holds the key order.

(defn- new-dict [] (with-meta {} {::order []}))

(defn- dict-put [dict k v]
  (if (contains? dict k)
    (assoc dict k v)
    (vary-meta (assoc dict k v) update ::order conj k)))

(defn- dict-keys [dict] (::order (meta dict)))
(defn- dict-entries [dict] (map (fn [k] [k (get dict k)]) (dict-keys dict)))
(defn- dict [& pairs] (reduce (fn [d [k v]] (dict-put d k v)) (new-dict) (partition 2 pairs)))

;; --- strict JSON, as Python's json.loads reads it ------------------------

(def ^:private max-int-digits 4300) ; sys.get_int_max_str_digits()

(defn- bad-json [message] (throw (ex-info message {::json-error true})))

(defn- json-ws? [c] (or (= c \space) (= c \tab) (= c \newline) (= c \return)))

(defn- skip-ws ^long [^String text ^long index]
  (let [length (.length text)]
    (loop [index index]
      (if (and (< index length) (json-ws? (.charAt text index))) (recur (inc index)) index))))

(def ^:private number-pattern #"-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?")

(defn- parse-number [^String text ^long index]
  (let [matcher (re-matcher number-pattern text)]
    (.region matcher (int index) (.length text))
    (when (.lookingAt matcher)
      (let [literal (.group matcher)
            end (+ index (count literal))]
        (if (or (.group matcher 1) (.group matcher 2))
          [(Double/parseDouble literal) end]
          (let [digit-count (cond-> (count literal) (str/starts-with? literal "-") dec)]
            (when (> digit-count max-int-digits)
              (bad-json "Exceeds the limit (4300 digits) for integer string conversion"))
            (let [big (BigInteger. ^String literal)]
              [(if (< (.bitLength big) 64) (.longValue big) big) end])))))))

(defn- hex-digit? [c]
  (or (<= (int \0) (int c) (int \9)) (<= (int \a) (int c) (int \f)) (<= (int \A) (int c) (int \F))))

(def ^:private string-special (re-pattern "[\"\\\\\\u0000-\\u001f]"))

(defn- parse-string-body
  "text[index] is just past the opening quote; [string end].  Runs of plain
  characters are found by a regex, not char by char (speed only)."
  [^String text ^long index]
  (let [length (.length text)
        builder (StringBuilder.)
        matcher (re-matcher string-special text)]
    (loop [index index]
      (when-not (.find matcher (int index)) (bad-json "Unterminated string"))
      (let [special (.start matcher)
            _ (.append builder text (int index) (int special))
            index special
            c (.charAt text index)]
        (cond
          (= c \") [(.toString builder) (inc index)]
          (= c \\)
          (do (when (>= (inc index) length) (bad-json "Unterminated string"))
              (let [escape (.charAt text (inc index))]
                (case escape
                  (\" \\ \/) (do (.append builder escape) (recur (+ index 2)))
                  \b (do (.append builder \backspace) (recur (+ index 2)))
                  \f (do (.append builder \formfeed) (recur (+ index 2)))
                  \n (do (.append builder \newline) (recur (+ index 2)))
                  \r (do (.append builder \return) (recur (+ index 2)))
                  \t (do (.append builder \tab) (recur (+ index 2)))
                  \u (let [hex-end (+ index 6)]
                       (when (or (> hex-end length)
                                 (not (every? hex-digit? (subs text (+ index 2) hex-end))))
                         (bad-json "Invalid \\uXXXX escape"))
                       ;; an escaped high surrogate followed by an escaped low
                       ;; one is one code point in Python; in a Java string the
                       ;; two chars are that same code point
                       (.append builder (char (Integer/parseInt (subs text (+ index 2) hex-end) 16)))
                       (recur hex-end))
                  (bad-json "Invalid \\escape"))))
          :else (bad-json "Invalid control character"))))))

(declare parse-value)

(defn- parse-array [^String text ^long index allow-constants]
  (let [index (skip-ws text index)]
    (if (and (< index (.length text)) (= (.charAt text index) \]))
      [[] (inc index)]
      (loop [items (transient []) index index]
        (let [[item index] (parse-value text index allow-constants)
              index (skip-ws text index)]
          (when (>= index (.length text)) (bad-json "Expecting ',' delimiter"))
          (case (.charAt text index)
            \] [(persistent! (conj! items item)) (inc index)]
            \, (let [index (skip-ws text (inc index))]
                 (when (and (< index (.length text)) (= (.charAt text index) \]))
                   (bad-json "Illegal trailing comma before end of array"))
                 (recur (conj! items item) index))
            (bad-json "Expecting ',' delimiter")))))))

(defn- parse-object
  "A dict: a repeated key keeps its first position and takes the last
  value, as a Python dict does."
  [^String text ^long index allow-constants]
  (let [index (skip-ws text index)]
    (if (and (< index (.length text)) (= (.charAt text index) \}))
      [(new-dict) (inc index)]
      (loop [result (new-dict) index index]
        (when-not (and (< index (.length text)) (= (.charAt text index) \"))
          (bad-json "Expecting property name enclosed in double quotes"))
        (let [[key-name index] (parse-string-body text (inc index))
              index (skip-ws text index)]
          (when-not (and (< index (.length text)) (= (.charAt text index) \:))
            (bad-json "Expecting ':' delimiter"))
          (let [[value index] (parse-value text (skip-ws text (inc index)) allow-constants)
                index (skip-ws text index)
                result (dict-put result key-name value)]
            (when (>= index (.length text)) (bad-json "Expecting ',' delimiter"))
            (case (.charAt text index)
              \} [result (inc index)]
              \, (recur result (skip-ws text (inc index)))
              (bad-json "Expecting ',' delimiter"))))))))

(defn- parse-value [^String text ^long index allow-constants]
  (when (>= index (.length text)) (bad-json "Expecting value"))
  (let [c (.charAt text index)
        literal (fn [word value]
                  (when (.startsWith text ^String word (int index)) [value (+ index (count word))]))
        constant (fn [word value]
                   (when (.startsWith text ^String word (int index))
                     ;; the last-line parse passes parse_constant=_reject_constant
                     (when-not allow-constants (bad-json (str word " is not JSON")))
                     [value (+ index (count word))]))]
    (or (case c
          \" (parse-string-body text (inc index))
          \{ (parse-object text (inc index) allow-constants)
          \[ (parse-array text (inc index) allow-constants)
          \n (literal "null" nil)
          \t (literal "true" true)
          \f (literal "false" false)
          nil)
        (parse-number text index)
        (constant "NaN" Double/NaN)
        (constant "Infinity" Double/POSITIVE_INFINITY)
        (constant "-Infinity" Double/NEGATIVE_INFINITY)
        (bad-json "Expecting value"))))

(defn read-json
  "Python's json.loads(text): exactly one value, whitespace around it.
  allow-constants: NaN, Infinity and -Infinity as bare json.loads takes them."
  [^String text allow-constants]
  (when (str/starts-with? text "﻿") (bad-json "Unexpected UTF-8 BOM"))
  (let [[value end] (parse-value text (skip-ws text 0) allow-constants)]
    (when (not= (skip-ws text end) (.length text)) (bad-json "Extra data"))
    value))

(defn- json-error? [error] (::json-error (ex-data error)))

;; --- Python's values: equality, repr, and the json.dumps printer ----------

(defn- py-int? [value] (or (instance? Long value) (instance? BigInteger value)))
(defn- py-float? [value] (instance? Double value))
(defn- py-dict? [value] (map? value))
(defn- py-list? [value] (vector? value))

(defn- to-big ^BigInteger [value]
  (cond (instance? BigInteger value) value
        (instance? Boolean value) (if value BigInteger/ONE BigInteger/ZERO)
        :else (BigInteger/valueOf (long value))))

(defn- py-number-equal [left right]
  (cond
    (and (py-float? left) (py-float? right)) (== (double left) (double right))
    (or (py-float? left) (py-float? right))
    (let [[float-side int-side] (if (py-float? left) [left right] [right left])
          d (double float-side)]
      (and (not (Double/isNaN d)) (not (Double/isInfinite d))
           (zero? (.compareTo (BigDecimal. d) (BigDecimal. (to-big int-side))))))
    :else (= (to-big left) (to-big right))))

(defn- py-numeric? [value] (or (py-int? value) (py-float? value) (instance? Boolean value)))

(defn py-equal
  "Python's ==: 1 == 1.0, True == 1, [True] == [1]; dicts by keys and values."
  [left right]
  (cond
    (and (py-numeric? left) (py-numeric? right)) (py-number-equal left right)
    (and (string? left) (string? right)) (= left right)
    (and (nil? left) (nil? right)) true
    (and (py-list? left) (py-list? right))
    (and (= (count left) (count right)) (every? true? (map py-equal left right)))
    (and (py-dict? left) (py-dict? right))
    (and (= (set (keys left)) (set (keys right)))
         (every? (fn [k] (py-equal (get left k) (get right k))) (keys left)))
    :else false))

(defn- shortest-digits
  "[digits decimal-point] of Python's repr for a finite, non-zero, positive
  double: the shortest decimal that rounds to it, closest when tied for
  length.  Java's Double.toString gives that, except that when one digit
  would do it may give two (4.9E-324 for 5e-324)."
  [d]
  (let [from-java (.stripTrailingZeros (BigDecimal. (Double/toString d)))
        one-digit (.stripTrailingZeros (.round (BigDecimal. (double d)) (MathContext. 1 RoundingMode/HALF_EVEN)))
        chosen (if (and (= 2 (.precision from-java))
                        (= d (Double/parseDouble (.toString one-digit))))
                 one-digit
                 from-java)
        digits (.toString (.unscaledValue chosen))]
    [digits (- (count digits) (.scale chosen))]))

(defn py-float-repr [d]
  (let [d (double d)]
    (cond
      (Double/isNaN d) "nan"
      (Double/isInfinite d) (if (pos? d) "inf" "-inf")
      (zero? d) (if (neg? (Double/doubleToRawLongBits d)) "-0.0" "0.0")
      :else
      (let [[digits point] (shortest-digits (Math/abs d))
            sign (if (neg? d) "-" "")
            length (count digits)]
        (str sign
             (if (or (<= point -4) (> point 16))
               (let [exponent (dec point)]
                 (str (subs digits 0 1)
                      (when (> length 1) (str "." (subs digits 1)))
                      "e" (if (neg? exponent) "-" "+")
                      (format "%02d" (Math/abs (long exponent)))))
               (cond
                 (<= point 0) (str "0." (apply str (repeat (- point) \0)) digits)
                 (>= point length) (str digits (apply str (repeat (- point length) \0)) ".0")
                 :else (str (subs digits 0 point) "." (subs digits point)))))))))

(defn- printable? [code-point]
  ;; Python's str.isprintable: not Cc Cf Cs Co Cn Zl Zp Zs, space excepted
  (or (= code-point 0x20)
      (not (#{Character/CONTROL Character/FORMAT Character/SURROGATE Character/PRIVATE_USE
              Character/UNASSIGNED Character/LINE_SEPARATOR Character/PARAGRAPH_SEPARATOR
              Character/SPACE_SEPARATOR}
            (Character/getType (int code-point))))))

(defn py-str-repr [^String text]
  (let [quote-char (if (and (str/includes? text "'") (not (str/includes? text "\""))) \" \')
        builder (StringBuilder.)]
    (.append builder quote-char)
    (doseq [code-point (iterator-seq (.iterator (.codePoints text)))]
      (let [code-point (int code-point)]
        (cond
          (or (= code-point (int quote-char)) (= code-point (int \\)))
          (.append (.append builder \\) (char code-point))
          (= code-point 9) (.append builder "\\t")
          (= code-point 10) (.append builder "\\n")
          (= code-point 13) (.append builder "\\r")
          (or (< code-point 0x20) (= code-point 0x7f)) (.append builder (format "\\x%02x" code-point))
          (< code-point 0x7f) (.append builder (char code-point))
          (printable? code-point) (.appendCodePoint builder code-point)
          (<= code-point 0xff) (.append builder (format "\\x%02x" code-point))
          (<= code-point 0xffff) (.append builder (format "\\u%04x" code-point))
          :else (.append builder (format "\\U%08x" code-point)))))
    (.append builder quote-char)
    (.toString builder)))

(defn py-repr [value]
  (cond
    (nil? value) "None"
    (true? value) "True"
    (false? value) "False"
    (py-int? value) (str value)
    (py-float? value) (py-float-repr value)
    (string? value) (py-str-repr value)
    (py-list? value) (str "[" (str/join ", " (map py-repr value)) "]")
    (py-dict? value) (str "{" (str/join ", " (for [[k v] (dict-entries value)] (str (py-repr k) ": " (py-repr v)))) "}")
    :else (throw (IllegalStateException. (str "no repr for " (type value))))))

(defn- py-str [value] (if (string? value) value (py-repr value)))

(defn- dumps-string [^String text]
  (let [builder (StringBuilder. "\"")]
    (dotimes [index (.length text)]
      (let [c (.charAt text index)]
        (case c
          \" (.append builder "\\\"")
          \\ (.append builder "\\\\")
          \newline (.append builder "\\n")
          \return (.append builder "\\r")
          \tab (.append builder "\\t")
          \backspace (.append builder "\\b")
          \formfeed (.append builder "\\f")
          (if (< (int c) 0x20)
            (.append builder (format "\\u%04x" (int c)))
            (.append builder c)))))
    (.append builder "\"")
    (.toString builder)))

(defn dumps
  "json.dumps(value, ensure_ascii=False): separators ', ' and ': '."
  [value]
  (cond
    (nil? value) "null"
    (true? value) "true"
    (false? value) "false"
    (py-int? value) (str value)
    (py-float? value) (let [d (double value)]
                        (cond (Double/isNaN d) "NaN"
                              (Double/isInfinite d) (if (pos? d) "Infinity" "-Infinity")
                              :else (py-float-repr d)))
    (string? value) (dumps-string value)
    (py-list? value) (str "[" (str/join ", " (map dumps value)) "]")
    (py-dict? value) (str "{" (str/join ", " (for [[k v] (dict-entries value)] (str (dumps-string k) ": " (dumps v)))) "}")
    :else (throw (IllegalStateException. (str "cannot dump " (type value))))))

(defn- surrogate-error
  "Python's print to a strict UTF-8 stdout fails on a lone surrogate: the
  UnicodeEncodeError message for `text`, or nil if it encodes."
  [^String text]
  (let [code-points (vec (iterator-seq (.iterator (.codePoints text))))
        surrogate? (fn [cp] (<= 0xD800 (int cp) 0xDFFF))
        start (first (keep-indexed (fn [i cp] (when (surrogate? cp) i)) code-points))]
    (when start
      (let [end (loop [end start] (if (and (< (inc end) (count code-points)) (surrogate? (code-points (inc end))))
                                    (recur (inc end)) end))]
        (if (= start end)
          (format "'utf-8' codec can't encode character '\\u%04x' in position %d: surrogates not allowed"
                  (int (code-points start)) start)
          (format "'utf-8' codec can't encode characters in position %d-%d: surrogates not allowed"
                  start end))))))

;; --- the subset validator --------------------------------------------------

(def implemented-keywords
  #{"type" "const" "enum" "required" "properties" "additionalProperties" "items" "oneOf"})

;; keywords checker.py does not implement and ignores, which the contract
;; schema uses; `pattern` is a validation keyword, ignored as checker.py ignores it
(def ignored-keywords #{"$schema" "$id" "title" "description" "pattern"})

(defn unknown-keywords
  "Every keyword in the schema that checker.py neither implements nor is
  known to ignore, with its path.  The twin refuses such a schema."
  ([schema] (unknown-keywords schema "$"))
  ([schema where]
   (if-not (py-dict? schema)
     [(str where " (not an object)")]
     (concat
      (for [k (dict-keys schema)
            :when (not (or (implemented-keywords k) (ignored-keywords k) (str/starts-with? k "x-")))]
        (str where "." k))
      (when-let [properties (get schema "properties")]
        (if (py-dict? properties)
          (mapcat (fn [[k sub]] (unknown-keywords sub (str where ".properties." k))) (dict-entries properties))
          [(str where ".properties (not an object)")]))
      (when (contains? schema "items") (unknown-keywords (get schema "items") (str where ".items")))
      (when-let [branches (get schema "oneOf")]
        (if (py-list? branches)
          (mapcat (fn [i sub] (unknown-keywords sub (str where ".oneOf[" i "]"))) (range) branches)
          [(str where ".oneOf (not an array)")]))))))

(defn- type-ok? [value type-name]
  (case type-name
    "null" (nil? value)
    "boolean" (instance? Boolean value)
    "integer" (py-int? value)
    "number" (or (py-int? value) (py-float? value))
    "string" (string? value)
    "array" (py-list? value)
    "object" (py-dict? value)
    (py-raise "ValueError" (str "unknown type " (py-str type-name)))))

(defn- json-equal [left right]
  (if (or (instance? Boolean left) (instance? Boolean right))
    (and (instance? Boolean left) (instance? Boolean right) (= left right))
    (py-equal left right)))

(defn- code-point-compare [^String left ^String right]
  (let [a (.toArray (.codePoints left)) b (.toArray (.codePoints right))]
    (loop [i 0]
      (cond (and (= i (alength a)) (= i (alength b))) 0
            (= i (alength a)) -1
            (= i (alength b)) 1
            (not= (aget a i) (aget b i)) (compare (aget a i) (aget b i))
            :else (recur (inc i))))))

(defn validate
  "nil if value conforms, else the first error found, in checker.py's order."
  ([value schema] (validate value schema "$"))
  ([value schema where]
   (or
    (when (contains? schema "type")
      (let [declared (get schema "type")
            allowed (if (py-list? declared) declared [declared])]
        (when-not (some #(type-ok? value %) allowed)
          (str where ": not of type " (py-repr (vec allowed))))))
    (when (and (contains? schema "const") (not (json-equal value (get schema "const"))))
      (str where ": not " (py-repr (get schema "const"))))
    (when (and (contains? schema "enum") (not (some #(json-equal value %) (get schema "enum"))))
      (str where ": not one of " (py-repr (get schema "enum"))))
    (when (py-dict? value)
      (let [properties (get schema "properties" (new-dict))]
        (or (some (fn [k] (when-not (contains? value k) (str where ": missing " (py-repr k))))
                  (get schema "required" []))
            (some (fn [[k sub]] (when (contains? value k) (validate (get value k) sub (str where "." k))))
                  (dict-entries properties))
            (when (false? (get schema "additionalProperties"))
              (let [extra (sort code-point-compare (remove #(contains? properties %) (dict-keys value)))]
                (when (seq extra) (str where ": unexpected " (py-repr (vec extra)))))))))
    (when (and (py-list? value) (contains? schema "items"))
      (some (fn [[i item]] (validate item (get schema "items") (str where "[" i "]")))
            (map-indexed vector value)))
    (when (contains? schema "oneOf")
      (let [matches (count (filter #(nil? (validate value % where)) (get schema "oneOf")))]
        (when (not= matches 1) (str where ": matches " matches " of oneOf, not 1")))))))

;; --- the checker -------------------------------------------------------------

(defn- py-split-dot [^String text] (vec (.split text "\\." -1)))

(defn- version-stop
  "The stop message, or nil if the newest hello announces `expected`."
  [lines ^String expected]
  (let [announced (reduce (fn [announced line]
                            (let [record (try (read-json line true)
                                              (catch clojure.lang.ExceptionInfo error
                                                (if (json-error? error) ::skip (throw error))))]
                              (if (and (py-dict? record) (py-equal (get record "event") "hello"))
                                (get record "contract")
                                announced)))
                          nil lines)
        expected-parts (py-split-dot expected)
        _ (when (< (count expected-parts) 2)
            (py-raise "ValueError" "not enough values to unpack (expected 2, got 1)"))
        [expected-major expected-minor] expected-parts]
    (when-not (and (string? announced) (= (vec (take 2 (py-split-dot announced))) [expected-major expected-minor]))
      (let [kind (if (and (string? announced) (= (first (py-split-dot announced)) expected-major)) "minor" "major")
            shown (if (string? announced) announced "(none)")]
        (str "contract " shown " from the producer, this consumer expects " expected
             " (" kind " update): check the schema and change log")))))

(defn- python-type-name [value]
  (cond (nil? value) "NoneType" (instance? Boolean value) "bool" (py-int? value) "int"
        (py-float? value) "float" (string? value) "str" (py-list? value) "list" :else "dict"))

(defn- getitem
  "value[key] for a str key, raising as Python does."
  [value key-name]
  (cond
    (py-dict? value) (if (contains? value key-name)
                       (get value key-name)
                       (py-raise "KeyError" (py-repr key-name)))
    (py-list? value) (py-raise "TypeError" "list indices must be integers or slices, not str")
    (string? value) (py-raise "TypeError" "string indices must be integers, not 'str'")
    :else (py-raise "TypeError" (str "'" (python-type-name value) "' object is not subscriptable"))))

(defn- strerror [^Exception error]
  (cond (instance? NoSuchFileException error) "No such file or directory"
        (= "java.nio.file.AccessDeniedException" (.getName (class error))) "Permission denied"
        (= "Is a directory" (.getMessage error)) "Is a directory"
        :else (.getMessage error)))

(defn- decode-utf8 [^bytes raw]
  (-> (.newDecoder StandardCharsets/UTF_8)
      (.onMalformedInput CodingErrorAction/REPORT)
      (.onUnmappableCharacter CodingErrorAction/REPORT)
      (.decode (ByteBuffer/wrap raw))
      (.toString)))


(defn check [^String log-path schema expected version-stop?]
  (let [raw (try (Files/readAllBytes (Paths/get log-path (make-array String 0)))
                 (catch java.io.IOException error error))]
    (if (instance? Exception raw)
      (dict "error" (str "unreadable: " (strerror raw)))
      (let [text (try (decode-utf8 raw) (catch CharacterCodingException _ nil))]
        (if (nil? text)
          (dict "error" "not UTF-8")
          (let [lines (vec (remove empty? (.split ^String text "\n" -1)))]
            (if (empty? lines)
              (dict "error" "empty log")
              (if-let [stop-message (and version-stop? (version-stop lines expected))]
                (dict "stopped" stop-message)
                (let [record (try (read-json (peek lines) false)
                                  (catch clojure.lang.ExceptionInfo error
                                    (if (json-error? error) ::not-json (throw error))))]
                  (if (= record ::not-json)
                    (dict "error" "last line is not JSON")
                    (if-let [error (validate record schema)]
                      (dict "error" (str "invalid: " error))
                      (let [result (dict "event" (getitem record "event"))]
                        (if (py-equal (getitem record "event") "snapshot")
                          (let [result (reduce (fn [result k] (dict-put result k (getitem record k)))
                                               result snapshot-keys)]
                            (dict-put result "input"
                                      (apply dict (mapcat (fn [k] [k (getitem (getitem record "input") k)])
                                                          input-keys))))
                          result)))))))))))))

;; --- command line, argparse's shape ------------------------------------------

(def ^:private options {"--expect" :expect "--no-version-stop" :no-version-stop})

(defn- usage-error [message]
  {:exit 2 :out "" :err (str "usage: checker.clj [-h] [--expect EXPECT] [--no-version-stop] log schema\n"
                             "checker.clj: error: " message "\n")})

(defn- parse-args
  "argparse: options anywhere, unique prefixes, --expect=V, `--` ends options."
  [args]
  (loop [args (seq args) parsed {:expect expected-contract :no-version-stop false :positional []}]
    (if-not args
      parsed
      (let [[token & more] args]
        (cond
          (= token "--") (update parsed :positional into more)
          (and (str/starts-with? token "--") (> (count token) 2))
          (let [[option-name inline] (str/split token #"=" 2)
                matches (filter #(str/starts-with? % option-name) (keys options))]
            (cond
              (not= 1 (count matches)) {:error (str "unrecognized arguments: " token)}
              (= (options (first matches)) :no-version-stop)
              (if inline {:error (str "argument --no-version-stop: ignored explicit argument '" inline "'")}
                  (recur more (assoc parsed :no-version-stop true)))
              inline (recur more (assoc parsed :expect inline))
              (or (nil? more) (str/starts-with? (first more) "-"))
              {:error "argument --expect: expected one argument"}
              :else (recur (next more) (assoc parsed :expect (first more)))))
          :else (recur more (update parsed :positional conj token)))))))

(defn run-cli
  "Run as `bb checker.clj ARGS`, without side effects: {:exit :out :err}.
  :out is the text checker.py would print on stdout."
  [args]
  (let [parsed (parse-args args)]
    (cond
      (:error parsed) (usage-error (:error parsed))
      (< (count (:positional parsed)) 2) (usage-error "the following arguments are required: log, schema")
      (> (count (:positional parsed)) 2) (usage-error (str "unrecognized arguments: " (str/join " " (drop 2 (:positional parsed)))))
      :else
      (try
        (let [[log-path schema-path] (:positional parsed)
              schema (read-json (try (String. (Files/readAllBytes (Paths/get schema-path (make-array String 0))) "UTF-8")
                                     (catch NoSuchFileException _
                                       (py-raise "FileNotFoundError"
                                                 (str "[Errno 2] No such file or directory: " (py-repr schema-path)))))
                                true)
              unknown (unknown-keywords schema)]
          (if (seq unknown)
            {:exit 2 :out ""
             :err (str "checker.clj: the schema uses keywords checker.py does not implement: "
                       (str/join ", " unknown) "\n")}
            (let [result (check log-path schema (:expect parsed) (not (:no-version-stop parsed)))
                  printed (dumps result)]
              (if-let [message (surrogate-error printed)]
                (py-raise "UnicodeEncodeError" message)
                {:exit (if (contains? result "event") 0 1) :out (str printed "\n") :err ""}))))
        (catch clojure.lang.ExceptionInfo error
          (cond
            (::py-exception (ex-data error))
            {:exit 1 :out "" :err (str "Traceback (most recent call last):\n  (checker.clj)\n"
                                       (::py-exception (ex-data error)) ": " (ex-message error) "\n")}
            (json-error? error)
            {:exit 1 :out "" :err (str "Traceback (most recent call last):\n  (checker.clj)\n"
                                       "json.decoder.JSONDecodeError: " (ex-message error) "\n")}
            :else (throw error)))))))

(defn- write-bytes [^java.io.PrintStream stream ^String text]
  (.write stream (.getBytes text StandardCharsets/UTF_8))
  (.flush stream))

(when (= *file* (System/getProperty "babashka.file"))
  (let [{:keys [exit out err]} (run-cli *command-line-args*)]
    (write-bytes System/out out)
    (write-bytes System/err err)
    (System/exit exit)))
