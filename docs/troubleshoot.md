# Troubleshooting log

Bugs found during development, how they presented, and what fixed them.
Kept so the same symptom doesn't get re-diagnosed from scratch next time.

## Traces detail pane renders completely blank

**Symptom**: On `/traces`, the trace list on the left loads fine (routes,
questions, durations, success badges all correct), but clicking a trace
— or auto-selecting the first one — leaves the entire right-hand detail
pane empty. Not "Loading trace…", not an error message, not the trace
header/tabs/graph — nothing at all. No console errors. Network tab shows
`GET /traces/<id>` returning `200` with a valid body.

**Root cause**: `frontend/src/services/traceService.ts`'s `getTrace()`
has return type `Promise<TraceDetail | { error: string }>` — the success
and failure shapes are told apart by presence of an `error` key.
But `TraceDetail` itself has a field `error: string | null` (the trace's
*own* execution status, e.g. whether the agent run failed). So a fully
successful response still has an `error` key (value `null`), and the
check in `frontend/src/pages/TracesPage.tsx` —

```ts
if ("error" in result) { ... }   // true for EVERY successful TraceDetail too
```

— always took the failure branch, setting both `detail` and
`detailError` to `null` (since `result.error` was `null`). With neither
set, none of the pane's three render branches (`loading` / `error` /
`detail`) matched, so nothing rendered at all — silently, since this is
a data-flow bug, not a thrown exception.

This was a pre-existing bug (the `error` field predates any recent
changes), so it affected 100% of trace detail views, always — not
specific to any one trace or route.

**Fix**: discriminate on a field that only exists on success instead —
`"trace_id" in result` — in the `getTrace(...).then(...)` handler in
`TracesPage.tsx`.

**Lesson**: when a service function returns `SuccessShape | { error:
string }`, check a field unique to `SuccessShape`, not merely `"error"
in result` — if the success shape ever gains a same-named field, the
check silently flips.

## Graph view doesn't match the branching design mockup

**Symptom**: The Traces → Graph tab rendered every step as a single
flat top-to-bottom list, regardless of actual execution shape — no
visual distinction between the route taken vs. not taken, and no
indication that verification/synthesis are parallel-ish tail steps. This
didn't match `assets/obs_traces.png` (the design target), which shows a
branching DAG: the router forking to a grayed-out "path not taken",
and the last two steps (verification, synthesis) forking from the prior
step and rejoining before "End", plus a corner minimap.

**Root cause**: not a bug — `frontend/src/components/observability/TraceGraph.tsx`
was only ever implemented as a linear list (`spans.map` straight down
the page with simple connectors); the branching layout in the mockup
was never built.

**Fix**: rebuilt `TraceGraph.tsx` around a computed coordinate layout
(`buildLayout`) instead of a plain list:
- Router branch: if the first span is `route` and `route` (prop, now
  threaded through from `TracesPage.tsx`) is `sql`/`rag`/`schema`, a
  grayed dashed "path not taken" node is drawn off to the side.
- Verification/synthesis fork: if the last two spans are `validating`
  then `synthesizing`, they're laid out as two nodes side-by-side that
  both stem from the prior step and both merge into `End`.
- A small SVG minimap (bottom-right, click-to-scroll) mirrors the same
  computed node/edge coordinates at a reduced scale.

**Lesson**: `TraceGraph` needs a `route` prop now — any other caller
must pass `detail.route` or it won't compile (`tsc --noEmit` catches
this immediately, which is what surfaced the transient blank-graph
report mid-session before the caller was updated).
