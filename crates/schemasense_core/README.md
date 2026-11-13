# schemasense-core

High-performance native acceleration core for SchemaSense AI, implemented in Rust with PyO3.

## Overview
`schemasense-core` is an optional binary extension for SchemaSense that provides:
- Accelerated columnar data profiling and SIMD outlier detection
- Fast schema snapshot diffing and topological dependency DAG analysis
- Zero-copy bounded binary GGUF and SafeTensors model metadata parsing
- Phased high-throughput SQLGuard AST security validation

## Installation
```bash
pip install schemasense-core
```
Or via the parent package extra:
```bash
pip install "schemasense[native]"
```

