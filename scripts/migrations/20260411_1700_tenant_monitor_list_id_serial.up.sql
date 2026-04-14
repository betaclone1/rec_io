-- Tenant monitor_list: ensure id has a per-schema sequence default.
-- Cloned / LIKE-created tables in users_NNNN often had NOT NULL id with no default,
-- so INSERT ... RETURNING id failed with null id.

DO $$
DECLARE
  r RECORD;
  sch text;
  slot text;
  slot_i int;
  tbl text;
  seq text;
  fq_table text;
  max_id bigint;
  floor_base bigint;
  band_lo int;
  band_hi int;
  linked text;
BEGIN
  FOR r IN
    SELECT nspname AS schema_name
    FROM pg_namespace
    WHERE nspname ~ '^users_[0-9]{4}$'
  LOOP
    sch := r.schema_name;
    slot := substring(sch FROM 'users_(.+)');
    tbl := 'monitor_list_' || slot;
    fq_table := sch || '.' || tbl;
    seq := tbl || '_id_seq';

    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name = tbl
    ) THEN
      CONTINUE;
    END IF;

    SELECT pg_get_serial_sequence(fq_table, 'id') INTO linked;
    IF linked IS NOT NULL THEN
      CONTINUE;
    END IF;

    EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I.%I AS INTEGER', sch, seq);

    slot_i := slot::integer;
    floor_base := slot_i * 10000;
    band_lo := floor_base + 1;
    band_hi := floor_base + 9999;

    -- Slot 0001: all ids count (includes legacy local 99xxx). Other slots: only ids in
    -- [slot*10000+1, slot*10000+9999] count so stray 99xxx rows do not pin the sequence.
    IF slot_i = 1 THEN
      EXECUTE format('SELECT COALESCE(MAX(id), 0) FROM %I.%I', sch, tbl) INTO max_id;
      EXECUTE format(
        'SELECT setval(%L::regclass, %s, true)',
        fq_table || '_id_seq',
        GREATEST(max_id, 10000)
      );
    ELSE
      EXECUTE format(
        'SELECT COALESCE(MAX(id), 0) FROM %I.%I WHERE id >= %s AND id <= %s',
        sch, tbl, band_lo, band_hi
      ) INTO max_id;
      EXECUTE format(
        'SELECT setval(%L::regclass, %s, true)',
        fq_table || '_id_seq',
        GREATEST(max_id, floor_base)
      );
    END IF;

    EXECUTE format(
      'ALTER TABLE %I.%I ALTER COLUMN id SET DEFAULT nextval(%L::regclass)',
      sch,
      tbl,
      fq_table || '_id_seq'
    );

    EXECUTE format(
      'ALTER SEQUENCE %I.%I OWNED BY %I.%I.id',
      sch,
      seq,
      sch,
      tbl
    );

    EXECUTE format(
      'GRANT USAGE, SELECT ON SEQUENCE %I.%I TO rec_io_user',
      sch,
      seq
    );
  END LOOP;
END
$$;
