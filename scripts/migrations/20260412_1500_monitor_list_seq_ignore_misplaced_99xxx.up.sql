-- Fix sequences for users_NNNN (N != 0001): MAX(id) over the whole table wrongly included
-- legacy 99xxx rows copied into tenant schemas, so nextval stayed in 99xxx.
-- Re-sync using only ids in [slot*10000+1, slot*10000+9999] for slot >= 2.

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
