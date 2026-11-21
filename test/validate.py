#!/usr/bin/env python3
"""validate.py SCHEMA FILE.jsonl... -- check every line against the schema.

Strict: each line must be UTF-8, parse as one JSON object (no NaN/Infinity,
no duplicate keys) and validate.  Uses the jsonschema package when it is
importable (`uv run --with jsonschema`), and always also runs a small
built-in validator for the subset the schema uses (type, const, enum,
required, properties, additionalProperties false, items, oneOf), so the two
cross-check each other.

    --expect-invalid   every line must FAIL (for the negative corpus)
Exit status 1 on any failure, with one message per bad line on stderr.
"""
import json
import sys

TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "null": lambda v: v is None,
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool)
    or (isinstance(v, float) and v.is_integer()),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}

SUPPORTED = {"$schema", "$id", "title", "description", "x-version", "type",
             "const", "enum", "required", "properties",
             "additionalProperties", "items", "oneOf"}


def same(a, b):
    """JSON equality: 1 == 1.0 but True != 1"""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def subset_errors(schema, value, path="$"):
    """errors for value against schema, using only the supported keywords"""
    unknown = set(schema) - SUPPORTED
    if unknown:
        raise SystemExit("validate.py: unsupported keywords %s" % sorted(unknown))
    errs = []
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(TYPES[t](value) for t in types):
            return ["%s: %r is not of type %s" % (path, value, types)]
    if "const" in schema and not same(schema["const"], value):
        errs.append("%s: %r != const %r" % (path, value, schema["const"]))
    if "enum" in schema and not any(same(e, value) for e in schema["enum"]):
        errs.append("%s: %r not in %r" % (path, value, schema["enum"]))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errs.append("%s: missing %r" % (path, key))
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                errs += subset_errors(sub, value[key], "%s.%s" % (path, key))
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errs.append("%s: unexpected key %r" % (path, key))
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errs += subset_errors(schema["items"], item, "%s[%d]" % (path, i))
    if "oneOf" in schema:
        ok = [i for i, sub in enumerate(schema["oneOf"])
              if not subset_errors(sub, value, path)]
        if len(ok) != 1:
            errs.append("%s: matches %d of oneOf (want exactly 1)" % (path, len(ok)))
    return errs


def no_constants(name):
    raise ValueError("non-standard JSON constant %s" % name)


def no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        raise ValueError("duplicate keys %s" % sorted(dup))
    return dict(pairs)


def parse(raw):
    text = raw.decode("utf-8")  # strict: raises on invalid UTF-8
    value = json.loads(text, parse_constant=no_constants,
                       object_pairs_hook=no_duplicates)
    if not isinstance(value, dict):
        raise ValueError("not a JSON object")
    return value


def main(argv):
    expect_invalid = "--expect-invalid" in argv
    args = [a for a in argv if a != "--expect-invalid"]
    if len(args) < 2:
        raise SystemExit(__doc__)
    schema = json.load(open(args[0]))
    try:
        import jsonschema
        full = jsonschema.Draft202012Validator(schema)
    except ImportError:
        full = None
    bad = checked = 0
    for name in args[1:]:
        data = open(name, "rb").read()
        if data and not data.endswith(b"\n"):
            print("%s: last line not newline-terminated" % name, file=sys.stderr)
            bad += 1
        for n, raw in enumerate(data.splitlines(), 1):
            checked += 1
            where = "%s:%d" % (name, n)
            disagree = False
            try:
                value = parse(raw)
                errs = subset_errors(schema, value)
                if full is not None:
                    ferrs = [e.message for e in full.iter_errors(value)]
                    if bool(ferrs) != bool(errs):
                        disagree = True
                        errs = ["validators disagree: jsonschema=%s subset=%s"
                                % (ferrs, errs)]
                    errs = errs or ferrs
            except ValueError as e:  # includes JSONDecodeError, UnicodeDecodeError
                errs = ["parse: %s" % e]
            if disagree:
                print("%s: %s" % (where, errs[0]), file=sys.stderr)
                bad += 1
            elif expect_invalid and not errs:
                print("%s: accepted, but should be invalid" % where, file=sys.stderr)
                bad += 1
            elif not expect_invalid and errs:
                print("%s: %s" % (where, "; ".join(errs)), file=sys.stderr)
                bad += 1
    print("validate: %d line(s), %d bad%s" % (checked, bad,
          "" if full else " (subset validator only)"), file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
