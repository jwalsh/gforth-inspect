#!/usr/bin/env bb
;; Test harness for experiment 007, not a consumer: runs the bb checker twin
;; on many argument vectors in one process, as the Python side imports
;; checker.py.  Each call goes through checker.clj's run-cli, the function
;; its command line runs, so the CLI and the driver cannot differ.
;;
;;     bb driver.clj jobs.json    (a JSON array of argument arrays)
;;
;; Prints a JSON array of {"exit": n, "out": "...", "err": "..."}.
(require '[babashka.classpath :as classpath]
         '[babashka.fs :as fs]
         '[cheshire.core :as json])
;; this directory is the source root: checker.clj is namespace `checker`
(classpath/add-classpath (str (fs/parent (fs/absolutize *file*))))
(require '[checker :as twin])
(let [jobs (json/parse-string (slurp (first *command-line-args*)))
      ;; jobs are independent (each reads its own files): run them in parallel
      results (pmap (fn [args]
                      (try (twin/run-cli args)
                           (catch Throwable error
                             {:exit 3 :out "" :err (str "twin crashed: " error)})))
                    jobs)]
  (.write System/out (.getBytes (json/generate-string (vec results)) "UTF-8"))
  (.flush System/out))
