#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

export EMBED_MODEL="sentence-transformers/all-MiniLM-L6-v2"
export EMBED_DIR="$ROOT_DIR/data/embeddings"
export ASSETS_DIR="$ROOT_DIR/assets/eval"
export RESULTS_DIR="$ROOT_DIR/results/eval"

python3 -m scripts.run_eval
