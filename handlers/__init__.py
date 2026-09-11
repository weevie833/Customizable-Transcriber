"""HTTP-handler mixins for app.py's Handler class, one module per feature
area -- mirrors pages/'s own precedent (one dedicated module per page)
rather than folding each feature's HTTP layer into its existing business-
logic package (xls_conversion/, index_compare/, test_mode/), which keeps
those packages free of any http.server/multipart-parsing awareness. See
docs/DESIGN.md's "Codebase structure" section.

Each module here defines one `*HandlerMixin` class of plain methods that
assume `self` is a `BaseHTTPRequestHandler` (specifically, app.py's
concrete `Handler`) -- they call `self.respond()`/`self.respond_json()`
and read `self.headers`/`self.rfile`, but the mixins never construct a
Handler themselves. app.py's `Handler` class composes all of them
alongside `BaseHTTPRequestHandler` and keeps only what's genuinely
cross-cutting: routing (do_GET/do_POST), the CSRF/Host/Origin security
checks, the generic response helpers, and static-asset serving.
"""
