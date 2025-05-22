"""initial schema

Revision ID: 20250422_221500
Revises: 
Create Date: 2025-04-22 22:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision = '20250422_221500'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Создаем таблицу users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('goal', sa.String(), nullable=True),
        sa.Column('emoji', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, default=datetime.utcnow),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_telegram_id'), 'users', ['telegram_id'], unique=True)
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)

    # Создаем таблицу completions
    op.create_table(
        'completions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade():
    op.drop_table('completions')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_index(op.f('ix_users_telegram_id'), table_name='users')
    op.drop_table('users') 