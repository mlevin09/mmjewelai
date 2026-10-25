# Reference Binding Contract v1.0.0

Status: **frozen and implemented as immutable runtime models; not yet persisted by
the application runtime**.

The contract records how one existing reference Asset relates to requested design
features. Feature relations are KEEP, CHANGE, LOCKED, INSPIRATION, or UNKNOWN.
Presentation bindings are separated from Product State.

Normative JSON shape: [schema-v1.0.0.json](schema-v1.0.0.json). Runtime models:
`jewelai_domain.reference_bindings`.

A binding is evidence/instruction and does not mutate Product State by itself.
