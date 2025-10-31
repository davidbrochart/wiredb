# WireDB

[![Build Status](https://github.com/davidbrochart/wiredb/workflows/test/badge.svg)](https://github.com/davidbrochart/wiredb/actions)
[![Code Coverage](https://img.shields.io/badge/coverage-100%25-green)](https://img.shields.io/badge/coverage-100%25-green)

WireDB is a distributed database based on [CRDTs](https://en.wikipedia.org/wiki/Conflict-free_replicated_data_type).
In particular, it uses [pycrdt](https://github.com/y-crdt/pycrdt), a Python library
providing bindings for [Yrs](https://github.com/y-crdt/y-crdt) (pronounce "wires"), the Rust port of [Yjs](https://github.com/yjs/yjs).

WireDB aims at making it easy to connect peers together through a variety of transport layers (called "wires").
Storage is provided as just another connection, for instance to a file.

[Read the documentation for more](https://davidbrochart.github.io/wiredb).
