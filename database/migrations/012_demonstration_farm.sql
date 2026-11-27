CREATE FUNCTION is_demonstration_farm(farm_id uuid, environment text) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT coalesce(farm_id = '44a5bb0c-6611-4d4b-9c93-88b81cfaae95' AND environment = 'simulation', false);
$$;

CREATE OR REPLACE FUNCTION validate_farm_limit_v3() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE limit_count int; current_count int;
BEGIN
 IF TG_OP='UPDATE' AND OLD.account_id IS NOT NULL AND NEW.account_id IS DISTINCT FROM OLD.account_id THEN
  RAISE EXCEPTION 'No se reasigna un predio a otro cliente' USING ERRCODE='23514';
 END IF;
 IF NEW.account_id IS NULL OR is_demonstration_farm(NEW.id, NEW.environment) THEN RETURN NEW; END IF;
 SELECT max_farms INTO STRICT limit_count FROM owner_accounts WHERE id=NEW.account_id FOR UPDATE;
 SELECT count(*) INTO current_count FROM farms
  WHERE account_id=NEW.account_id AND active AND id<>NEW.id AND NOT is_demonstration_farm(id, environment);
 IF NEW.active AND current_count>=limit_count THEN
  RAISE EXCEPTION 'Cupo de predios excedido' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
