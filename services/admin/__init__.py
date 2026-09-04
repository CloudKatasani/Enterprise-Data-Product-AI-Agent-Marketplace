"""Administration (M12.2): rubrics, taxonomies, connectors, flags and tenancy.

The admin console changes configuration, never records. It can publish a new
rubric version; it cannot edit one that exists. It can toggle a flag; it cannot
edit an audit event, a snapshot or a grant, because those tables are append-only
at the database and no console can talk its way past a trigger.

That distinction is the whole design. An administrator is a role with wide
authority over *what the rules are* and no authority at all over *what
happened*, and an estate where those are the same permission cannot be audited.
"""
