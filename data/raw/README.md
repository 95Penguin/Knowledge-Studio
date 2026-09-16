# Raw data

Raw external corpora are reproducible build inputs and are not committed to this repository.

Fetch the Redis corpus from the project root:

```bash
./scripts/fetch_redis_docs.sh
```

The command creates `data/raw/redis-docs/source/` and a generated
`data/raw/redis-docs/CORPUS_MANIFEST.yaml`. The manifest records the exact
upstream commit and file hashes. Do not edit a generated snapshot in place.

To rebuild from a commit that is already present in `.cache/redis-docs`
without accessing the network:

```bash
REDIS_DOCS_OFFLINE=1 REDIS_DOCS_COMMIT=<commit> ./scripts/fetch_redis_docs.sh
```
