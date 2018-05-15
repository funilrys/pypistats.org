"""add indexes

Revision ID: a91799876ec2
Revises: e65ba8f3cdcf
Create Date: 2018-05-14 22:27:11.123192

"""
# flake8: noqa
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a91799876ec2'
down_revision = 'e65ba8f3cdcf'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_index(op.f('ix_overall_package'), 'overall', ['package'], unique=False)
    op.create_index(op.f('ix_python_major_package'), 'python_major', ['package'], unique=False)
    op.create_index(op.f('ix_python_minor_package'), 'python_minor', ['package'], unique=False)
    op.create_index(op.f('ix_recent_package'), 'recent', ['package'], unique=False)
    op.create_index(op.f('ix_system_package'), 'system', ['package'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_system_package'), table_name='system')
    op.drop_index(op.f('ix_recent_package'), table_name='recent')
    op.drop_index(op.f('ix_python_minor_package'), table_name='python_minor')
    op.drop_index(op.f('ix_python_major_package'), table_name='python_major')
    op.drop_index(op.f('ix_overall_package'), table_name='overall')
    # ### end Alembic commands ###
