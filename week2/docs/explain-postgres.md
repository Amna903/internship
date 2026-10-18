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
