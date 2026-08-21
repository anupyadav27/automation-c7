"""store.rules — rule definitions ⋈ authored metadata (the registry)."""
from . import get_backend, is_postgres


def list_rules(kind=None, limit=500, offset=0):
    backend = get_backend()
    if is_postgres():
        where, params = ["1=1"], []
        if kind:
            where.append("d.rule_kind = %s")
            params.append(kind)
        total = backend.query_one(
            f"SELECT count(*) AS n FROM rules_definitions d WHERE {' AND '.join(where)}",
            params)["n"]
        rows = backend.query(
            f"""SELECT d.*, m.title, m.description AS meta_description,
                       m.rationale, m.recommendation, m.ai_fix_prompt,
                       m."references", m.frameworks
                FROM rules_definitions d
                LEFT JOIN rules_metadata m ON m.rule_id = d.rule_id
                WHERE {' AND '.join(where)} ORDER BY d.rule_id
                LIMIT %s OFFSET %s""", params + [limit, offset])
        return rows, total

    registry = backend.read("registry", default={}) or {}
    rows = [{"rule_id": rid, **entry} for rid, entry in sorted(registry.items())
            if kind is None or entry.get("kind") == kind]
    return backend.paginate(rows, limit, offset)


def get_rule(rule_id):
    backend = get_backend()
    if is_postgres():
        return backend.query_one(
            """SELECT d.*, m.title, m.description AS meta_description, m.rationale,
                      m.recommendation, m.ai_fix_prompt, m."references", m.frameworks
               FROM rules_definitions d
               LEFT JOIN rules_metadata m ON m.rule_id = d.rule_id
               WHERE d.rule_id = %s""", [rule_id])
    registry = backend.read("registry", default={}) or {}
    entry = registry.get(rule_id)
    return {"rule_id": rule_id, **entry} if entry else None
