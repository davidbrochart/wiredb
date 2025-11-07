WireDB can be installed through [PyPI](https://pypi.org) or [conda-forge](https://conda-forge.org).

## With `pip`

```bash
pip install wiredb  # no wire installed
pip install "wiredb[websocket,file]"  # with wires "websocket" and "file"
```

## With `micromamba`

We recommend using `micromamba` to manage `conda-forge` environments (see `micromamba`'s
[installation instructions](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html)).
First create an environment, here called `my_env`, and activate it:
```bash
micromamba create -n my_env
micromamba activate my_env
```

Then install `wiredb`.

```bash
micromamba install wiredb
micromamba install wire-websocket wire-file  # install wires for WebSocket and file
```

## Development install

You first need to clone the repository:

```bash
git clone https://github.com/davidbrochart/wiredb
cd wiredb
```

We recommend using [uv](https://docs.astral.sh/uv). First create a virtual environment and activate it.

```bash
uv venv
source .venv/bin/activate  # on linux
```

Then install `wiredb` in editable mode:
```bash
uv pip install -e ".[websocket,file]"
```
