WireDB is a distributed database based on [CRDTs](https://en.wikipedia.org/wiki/Conflict-free_replicated_data_type).
In particular, it uses [pycrdt](https://github.com/y-crdt/pycrdt), a Python library
providing bindings for [Yrs](https://github.com/y-crdt/y-crdt) (pronounce "wires"), the Rust port of [Yjs](https://github.com/yjs/yjs).

WireDB aims at making it easy to connect peers together through a variety of transport layers (called "wires").
Storage is provided as just another connection, for instance to a file.
