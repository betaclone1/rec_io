-- Resync monitor_list_*_id_seq for slot-prefixed ids.
-- Slot 0001: next = GREATEST(MAX(all ids), 10000) + 1 (keeps 99xxx + 1xxxx).
-- Slots >= 0002: next from MAX(id) only within [slot*10000+1, slot*10000+9999], so
-- mistaken 99xxx rows in tenant tables do not consume the sequence.

DO $$
DECLARE
  r RECORD;
  sch text;
  slot text;
  slot_i int;
  tbl text;
  fq_seq text;
  mx bigint;
  floor_base bigint;
  band_lo int;
  band_hi int;
  new_last bigint;
BEGIN
  FOR r IN
    SELECT nspname AS schema_name
    FROM pg_namespace
    WHERE nspname ~ '^users_[0-9]{4}$'
  LOOP
    sch := r.schema_name;
    PERFORM set_config('rec.tenant_pg_schema', sch, true);
    slot := substring(sch FROM 'users_(.+)');
    tbl := 'monitor_list_' || slot;
    fq_seq := sch || '.' || tbl || '_id_seq';

    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name = tbl
    ) THEN
      CONTINUE;
    END IF;

    IF to_regclass(fq_seq) IS NULL THEN
      CONTINUE;
    END IF;

    slot_i := slot::integer;
    floor_base := slot_i * 10000;
    band_lo := floor_base + 1;
    band_hi := floor_base + 9999;

    IF slot_i = 1 THEN
      EXECUTE format('SELECT COALESCE(MAX(id), 0) FROM %I.%I', sch, tbl) INTO mx;
      new_last := GREATEST(mx, 10000);
    ELSE
      EXECUTE format(
        'SELECT COALESCE(MAX(id), 0) FROM %I.%I WHERE id >= %s AND id <= %s',
        sch, tbl, band_lo, band_hi
      ) INTO mx;
      new_last := GREATEST(mx, floor_base);
    END IF;

    EXECUTE format('SELECT setval(%L::regclass, %s, true)', fq_seq, new_last);
  END LOOP;
END
$$;
