# Version history

## 0.7.0

This is a big refactor to get rid of the `connect` and `bind` functions, and the entry-points where wires are registered.
Instead, one directly uses the synchronous or asynchronous client and server classes. Also, `auto_update` has been replaced
with `auto_push`/`auto_pull`. Note that synchronous clients only have `auto_push`, because they must manually call `pull()` anyway.
This is due to the fact that it's not possible to receive updates in a thread because `pycrdt` doesn't allow multithreading, so
`auto_pull` for a synchronous client would just block everything.

## 0.6.2

- Add client `synchronized` event.

## 0.6.1

- Add sync API for `wire-file` and `wire-websocket`.
- Remove `Provider`.

## 0.5.0

- Support cookies in `wire-websocket`.
- Support update push/pull.

## 0.4.0

- Add `room_factory` parameter to `bind`.
- Add documentation.

## 0.3.0

- Support squashing file updates.
- Add file versioning.

## 0.2.1

- Clean room when clients leave.

## 0.2.0

- Add support for connected server rooms.

## 0.1.3

- Add file wire.

## 0.1.2

- Allow passing a doc to a client.

## 0.1.1

- Add wire for communicating over pipe.

## 0.1.0

- Initial release with client/server architecture.
