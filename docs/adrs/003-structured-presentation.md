# ADR 003: Narrow structured presentation

Status: accepted.

Callers own record selection, headings, order, and display-ready strings. The
library owns escaping, conservative layouts, limits, and explicit omission counts.
`NotificationTable` is optional and deliberately excludes HTML, callbacks, record
mapping, nesting, and general templates.
