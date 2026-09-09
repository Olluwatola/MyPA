from fastcrud import FastCRUD

from ..models.goal import Goal
from ..schemas.goal import GoalCreateInternal, GoalDelete, GoalRead, GoalUpdate, GoalUpdateInternal

CRUDGoal = FastCRUD[Goal, GoalCreateInternal, GoalUpdate, GoalUpdateInternal, GoalDelete, GoalRead]
crud_goals = CRUDGoal(Goal)
