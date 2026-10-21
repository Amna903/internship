# EXPLAIN evidence (PostgreSQL 16, ~20,000 synthetic profiles)

Produced with `python manage.py seed_demo --bulk 20000`, `ANALYZE`, then `EXPLAIN (ANALYZE, BUFFERS)`.
The planner was **not** coerced (no `enable_seqscan=off`). The `explain_queries` management command
does that coercion on tiny tables only, so a small demo still shows the index it *would* use.

## 1. Admin list: `WHERE status='active' ORDER BY created_at DESC LIMIT 10`

Index: `hp_status_created_idx` on `(status, created_at DESC)`.

**With the index: 2.9 ms. No sort step; the LIMIT stops after 10 index entries.**

```
Limit  (cost=0.29..2.06 rows=10 width=33) (actual time=2.912..2.920 rows=10 loops=1)
  ->  Index Scan using hp_status_created_idx on profiles_healthprofile
        Index Cond: ((status)::text = 'active'::text)
Execution Time: 2.945 ms
```

**Same query with the index dropped: 14.1 ms. Reads every active row, then sorts.**

```
Limit  (cost=1368.42..1368.45 rows=10 width=33) (actual time=14.121..14.126 rows=10 loops=1)
  ->  Sort  Sort Key: created_at DESC   Sort Method: top-N heapsort  Memory: 25kB
        ->  Seq Scan on profiles_healthprofile  (actual rows=17971)
              Filter: ((status)::text = 'active'::text)
              Rows Removed by Filter: 2035
Execution Time: 14.157 ms
```

Why it works: equality on the leading column (`status`) followed by the sort column means rows are
already stored in the order the query wants, so Postgres reads 10 entries and stops.

Honest caveat: ~90% of rows are `active`, so the filter itself is not selective. The win is
avoiding the full sort, and it grows with table size (the no-index cost is O(n log n)-ish, the index
cost stays roughly constant for a fixed page). At 20k rows it is ~5x; do not expect it to matter at 6 rows.

## 2. Login lookup: `WHERE email = ?`

Index: the unique constraint on `accounts_user.email` (Django also creates a `_like` index for LIKE queries).

```
Index Scan using accounts_user_email_b2644a56_like on accounts_user
  Index Cond: ((email)::text = 'amina.rahman@example.test'::text)
Execution Time: 0.053 ms
```

---

# Week 2 indexes (PostgreSQL 14.21, 20,006 profiles, 60,000 audit events)

Produced with `seed_demo --bulk 20000`, 60,000 synthetic audit events, `ANALYZE`, then
`EXPLAIN (ANALYZE, BUFFERS)`. "Without" = same query inside `BEGIN; DROP INDEX …; EXPLAIN …; ROLLBACK;`.
No planner coercion.

## 4. Admin follow-up list: `WHERE completion_status='incomplete' ORDER BY created_at DESC LIMIT 10`

Index: `hp_completion_created_idx` on `(completion_status, created_at DESC)`. 7,991 of 20,006 rows are incomplete.

**With the index: 0.20 ms, 78 buffers.** Reads 10 index entries and stops.
```
Limit  (actual time=0.180..0.186 rows=10 loops=1)
  ->  Index Scan using hp_completion_created_idx on profiles_healthprofile
        Index Cond: ((completion_status)::text = 'incomplete'::text)
Execution Time: 0.197 ms
```
**Without: 5.5 ms, 903 buffers.** Scans the whole table and sorts.
```
Limit  (actual time=5.516..5.517 rows=10 loops=1)
  ->  Sort  Sort Key: created_at DESC  Sort Method: top-N heapsort
        ->  Seq Scan on profiles_healthprofile  (actual rows=7991)
              Filter: ((completion_status)::text = 'incomplete'::text)
              Rows Removed by Filter: 12015
Execution Time: 5.534 ms
```

## 5. One profile's audit history: `WHERE profile_id=? ORDER BY created_at DESC LIMIT 20`

> **Update (review fixes):** the history filter now uses `subject_profile_id`, a copy of the id that
> survives profile deletion, with its own index `audit_subject_created_idx` of the same shape. The
> PostgreSQL timings below were measured on the earlier `profile_id` query and have not been re-run;
> `python manage.py explain_queries` confirms the new query uses the new index (SQLite). The
> `profile_id` index stays, because deleting a profile must find its rows to set the FK to NULL.

Index: `audit_profile_created_idx` on `(profile_id, created_at DESC)`.

**With the index: 0.08 ms, 20 buffers.**
```
Limit  (actual time=0.052..0.053 rows=12 loops=1)
  ->  Sort  Sort Key: created_at DESC  Sort Method: quicksort  Memory: 26kB
        ->  Bitmap Heap Scan on audit_auditevent  (actual rows=12)
              ->  Bitmap Index Scan on audit_profile_created_idx
                    Index Cond: (profile_id = 8504)
Execution Time: 0.077 ms
```
**Without: 7.0 ms, 782 buffers.** Reads all 60,000 events to find 12.
```
Limit  (actual time=6.968..6.970 rows=12 loops=1)
  ->  Sort  Sort Key: created_at DESC
        ->  Seq Scan on audit_auditevent  Filter: (profile_id = 8504)  Rows Removed by Filter: 59988
Execution Time: 6.989 ms
```
With only ~12 matching rows the planner chose a bitmap scan plus a tiny in-memory sort instead of
walking the index in order; both are cheap. The index matters because it turns "scan 60k rows" into
"read 12".

**Redundant index removed.** Django adds a single-column index to every foreign key. The first run
showed `audit_auditevent_profile_id_…` next to the composite index. Dropping it changed nothing
(the plan above uses the composite either way, 0.115 ms vs 0.077 ms is noise), because the composite's
leading column is already `profile_id`. So the FK is declared with `db_index=False`, saving a write on
every audit insert.
