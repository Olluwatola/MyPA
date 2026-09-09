from fastcrud import FastCRUD

from ..models.memory_extraction_record import MemoryExtractionRecord
from ..schemas.memory_extraction_record import MemoryExtractionRecordCreate, MemoryExtractionRecordRead

# Append-only table — MemoryExtractionRecordCreate reused for Update/UpdateInternal/Delete
# generic slots too (same trick as crud_token_blacklist.py); nothing ever updates or
# deletes a record.
CRUDMemoryExtractionRecord = FastCRUD[
    MemoryExtractionRecord,
    MemoryExtractionRecordCreate,
    MemoryExtractionRecordCreate,
    MemoryExtractionRecordCreate,
    MemoryExtractionRecordCreate,
    MemoryExtractionRecordRead,
]
crud_memory_extraction_records = CRUDMemoryExtractionRecord(MemoryExtractionRecord)
