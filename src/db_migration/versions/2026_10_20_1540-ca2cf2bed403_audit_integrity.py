"""audit integrity: append-only triggers and a hash chain

Revision ID: ca2cf2bed403
Revises: 2ac292123110
Create Date: 2026-10-20 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ca2cf2bed403'
down_revision: Union[str, Sequence[str], None] = '2ac292123110'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The hashed content of an event, in a fixed text form. actor_id is deliberately left out:
# deleting a user sets it to NULL, the one change the append-only rule allows.
EVENT_HASH = """
    encode(sha256(convert_to(concat_ws('|',
        e.seq::text,
        e.id::text,
        to_char(e.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
        e.event_type,
        coalesce(e.ip, ''),
        coalesce(e.user_agent, ''),
        e.details::text,
        coalesce(e.prev_hash, '')
    ), 'UTF8')), 'hex')
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SEQUENCE audit_events_seq")
    op.add_column('audit_events', sa.Column('seq', sa.BigInteger(), nullable=True))
    op.add_column('audit_events', sa.Column('prev_hash', sa.String(length=64), nullable=True))
    op.add_column('audit_events', sa.Column('hash', sa.String(length=64), nullable=True))

    # Chain the events recorded so far, oldest first
    op.execute(
        """
        UPDATE audit_events a SET seq = o.n
        FROM (SELECT id, row_number() OVER (ORDER BY created_at, id) AS n FROM audit_events) o
        WHERE a.id = o.id
        """
    )
    op.execute("SELECT setval('audit_events_seq', coalesce((SELECT max(seq) FROM audit_events), 0) + 1, false)")
    op.execute(
        f"""
        DO $$
        DECLARE r record; prev text := NULL;
        BEGIN
          FOR r IN SELECT id FROM audit_events ORDER BY seq LOOP
            UPDATE audit_events e SET prev_hash = prev WHERE e.id = r.id;
            UPDATE audit_events e SET hash = {EVENT_HASH} WHERE e.id = r.id
              RETURNING hash INTO prev;
          END LOOP;
        END $$
        """
    )
    op.alter_column('audit_events', 'seq', nullable=False, server_default=sa.text("nextval('audit_events_seq')"))
    op.alter_column('audit_events', 'hash', nullable=False)
    op.create_unique_constraint(op.f('uq_audit_events_seq'), 'audit_events', ['seq'])
    op.execute("ALTER SEQUENCE audit_events_seq OWNED BY audit_events.seq")

    # Every new event links to the previous one. The advisory lock serializes inserts so
    # two transactions can't both chain onto the same predecessor.
    op.execute(
        f"""
        CREATE FUNCTION audit_events_chain() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE e audit_events%ROWTYPE;
        BEGIN
          PERFORM pg_advisory_xact_lock(7240071);
          NEW.prev_hash := (SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1);
          e := NEW;
          NEW.hash := {EVENT_HASH};
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_chain BEFORE INSERT ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_chain()"
    )

    # Append-only: no edits; deletes only by the retention purge (which says so explicitly)
    op.execute(
        """
        CREATE FUNCTION audit_events_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF NEW.actor_id IS NULL AND OLD.actor_id IS NOT NULL
               AND (NEW.id, NEW.seq, NEW.created_at, NEW.event_type, NEW.ip, NEW.user_agent,
                    NEW.details, NEW.prev_hash, NEW.hash)
                   IS NOT DISTINCT FROM
                   (OLD.id, OLD.seq, OLD.created_at, OLD.event_type, OLD.ip, OLD.user_agent,
                    OLD.details, OLD.prev_hash, OLD.hash) THEN
              RETURN NEW;  -- a deleted user's events lose the link to them, nothing else
            END IF;
            RAISE EXCEPTION 'audit_events is append-only: events cannot be changed';
          END IF;
          IF coalesce(current_setting('finance_acc.audit_purge', true), '') = 'on' THEN
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NULL END;
          END IF;
          RAISE EXCEPTION 'audit_events is append-only: events are removed only by the retention purge';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_guard BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_guard()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_guard_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_guard()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER audit_events_guard_truncate ON audit_events")
    op.execute("DROP TRIGGER audit_events_guard ON audit_events")
    op.execute("DROP TRIGGER audit_events_chain ON audit_events")
    op.execute("DROP FUNCTION audit_events_guard()")
    op.execute("DROP FUNCTION audit_events_chain()")
    op.drop_constraint(op.f('uq_audit_events_seq'), 'audit_events', type_='unique')
    op.drop_column('audit_events', 'hash')
    op.drop_column('audit_events', 'prev_hash')
    op.drop_column('audit_events', 'seq')
