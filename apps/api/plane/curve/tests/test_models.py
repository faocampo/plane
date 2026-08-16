import pytest

from plane.curve.models import WorkspaceScopedModel


pytestmark = pytest.mark.unit


def test_workspace_scoped_model_is_abstract_and_creates_no_table():
    assert WorkspaceScopedModel._meta.abstract is True
    assert WorkspaceScopedModel._meta.db_table not in {
        "db_workspace",
        "db_workspacemember",
    }


def test_workspace_scoped_model_has_normative_common_fields():
    assert {field.name for field in WorkspaceScopedModel._meta.fields} == {
        "id",
        "workspace_id",
        "aggregate_version",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "tombstoned_at",
        "tombstoned_by",
        "tombstone_reason",
    }
