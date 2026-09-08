import asyncio
import logging

from sqlalchemy import select

from ..app.core.config import settings
from ..app.core.db.database import AsyncSession, local_session
from ..app.core.security import get_password_hash
from ..app.models.user import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_first_user(session: AsyncSession) -> None:
    email = settings.ADMIN_EMAIL

    query = select(User).filter_by(email=email)
    result = await session.execute(query)
    user = result.scalar_one_or_none()

    if user is not None:
        logger.info(f"Admin user {email} already exists.")
        return

    admin = User(
        name=settings.ADMIN_NAME,
        email=email,
        hashed_password=get_password_hash(settings.ADMIN_PASSWORD),
        is_superuser=True,
    )
    session.add(admin)
    await session.commit()
    logger.info(f"Admin user {email} created successfully.")


async def main() -> None:
    async with local_session() as session:
        await create_first_user(session)


if __name__ == "__main__":
    asyncio.run(main())
