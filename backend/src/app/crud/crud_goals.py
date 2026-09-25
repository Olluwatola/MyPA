from fastcrud import FastCRUD

from ..models.goal import Goal
from ..schemas.goal import GoalCreateInternal, GoalDelete, GoalRead, GoalUpdate, GoalUpdateInternal

# `delete()` is a soft delete (Goal has is_deleted/deleted_at); `db_delete()` would hard
# delete and is never called. FastCRUD does not filter soft-deleted rows on reads — pass
# `is_deleted=False` explicitly.
CRUDGoal = FastCRUD[Goal, GoalCreateInternal, GoalUpdate, GoalUpdateInternal, GoalDelete, GoalRead]
crud_goals = CRUDGoal(Goal)
