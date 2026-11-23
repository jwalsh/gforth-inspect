"""The OpenAPI draft under three validators (openapi-spec-validator 0.9.0).

    uv run --no-project --with openapi-spec-validator==0.9.0 python oas_check.py ../openapi-stacks.json

Like I-1 for the stream, the `openapi` field makes an older tool fail early,
on the version string, before it reads the schema.
"""
import json, sys
from openapi_spec_validator import OpenAPIV31SpecValidator, OpenAPIV30SpecValidator, OpenAPIV2SpecValidator
doc = json.load(open(sys.argv[1]))
def errs(V, d):
    return [e.message[:90] for e in V(d).iter_errors()]
print("3.1:", errs(OpenAPIV31SpecValidator, doc))
print("3.0 as is:", errs(OpenAPIV30SpecValidator, doc)[:3])
relabel = dict(doc, openapi="3.0.3"); relabel.pop("jsonSchemaDialect", None)
e = errs(OpenAPIV30SpecValidator, relabel); print("3.0 relabelled:", len(e), e[:8])
print("2.0:", errs(OpenAPIV2SpecValidator, doc)[:3])
