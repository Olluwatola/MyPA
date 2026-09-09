from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.dependencies import get_current_user
from ...core.db.database import async_get_db
from ...core.llm.extraction import run_memory_extraction_pipeline
from ...schemas.memory_extraction_record import MemoryExtractionRecordRead

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["conversation", "email", "calendar", "notion"]
    source_channel: Literal["in_app", "telegram"] | None = None
    content: Annotated[str, Field(min_length=1, examples=["Remind me to send the invoice to Acme by Friday."])]


@router.post("/ingest", response_model=MemoryExtractionRecordRead, status_code=201)
async def write_memory_ingest(
    payload: MemoryIngestRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    return await run_memory_extraction_pipeline(
        db=db,
        user_id=current_user["id"],
        source_type=payload.source_type,
        source_channel=payload.source_channel,
        content=payload.content,
    )
