#!/usr/bin/env bb
;; Reference consumer 3, the bb twin of pbt/consumers/mock_server.py (experiment 007).
;;
;;     bb mock_server.clj path/to/stacks.jsonl
;;
;; Binds 127.0.0.1 on an ephemeral port and prints `PORT <n>` on stdout.
;; GET /stacks serves the last line of the file, byte for byte (without its
;; newline), as application/json.  The file is read on every request, so it
;; behaves like `tail -1` on a live log.  404 when the file is missing or
;; holds no line, and for any other path (the request target must be
;; /stacks, as mock_server.py compares self.path, after http.server has
;; collapsed leading slashes).  A method other than GET
;; gets 501, as http.server answers a handler without do_<METHOD>.
;; Nothing beyond babashka: http-kit is bundled.

(ns mock-server
  (:require [org.httpkit.server :as server])
  (:import (java.nio.file Files Paths)
           (java.util Arrays)))

(defn last-line
  "The last non-empty LF-separated line of the file, as bytes, or nil."
  [log-path]
  (when-let [^bytes content (try (Files/readAllBytes (Paths/get log-path (make-array String 0)))
                                 (catch java.io.IOException _ nil))]
    (let [end (loop [end (alength content)]
                (if (and (pos? end) (= 10 (aget content (dec end)))) (recur (dec end)) end))]
      (when (pos? end)
        (let [start (loop [start end]
                      (if (and (pos? start) (not= 10 (aget content (dec start)))) (recur (dec start)) start))]
          (Arrays/copyOfRange content (int start) (int end)))))))

(defn request-path
  "self.path as http.server sets it: a leading run of slashes is collapsed
  to one (CPython gh-87389), so //stacks is /stacks."
  [^String uri]
  (if (.startsWith uri "//") (str "/" (.replaceFirst uri "^/+" "")) uri))

(defn handler [log-path]
  (fn [request]
    (cond
      (not= :get (:request-method request)) {:status 501 :body ""}
      (not (and (= "/stacks" (request-path (:uri request))) (nil? (:query-string request))))
      {:status 404 :body ""}
      :else (if-let [body (last-line log-path)]
              {:status 200 :headers {"Content-Type" "application/json"} :body body}
              {:status 404 :body ""}))))

(when (= *file* (System/getProperty "babashka.file"))
  (let [log-path (first *command-line-args*)
        running (server/run-server (handler log-path) {:ip "127.0.0.1" :port 0 :legacy-return-value? false})]
    (println "PORT" (server/server-port running))
    (flush)
    @(promise)))
