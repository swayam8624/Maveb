# Gaussian Index Layout Probe v2

At one million synthetic Gaussians, the first hash-bucket prototype is not an obvious production choice.

| layout | build | 1%-dirty lookup | max RSS |
|---|---:|---:|---:|
| hash buckets | 263.6 ms | 0.312 ms | 88,424 KiB |
| sorted packed-key vector | 107.2 ms | 2.013 ms | 37,160 KiB |

These are Linux sandbox numbers, not MAVEB/M2 results. RSS includes common process/input memory.

The result suggests a production architecture worth testing:

```
compact sorted immutable base index
              +
small mutable delta overlay for moved/new/removed Gaussians
              ↓
periodic compaction when delta exceeds threshold
```

That structure could preserve sparse-query locality without allocating a heavyweight hash bucket for most persistent world state. It also fits append-only world revisions better than rebuilding a monolithic index every edit.

**Do not claim a result yet.** Next measure exact lookup equivalence, delta maintenance, compaction crossover, bytes per Gaussian, and M2 Pro behavior.
