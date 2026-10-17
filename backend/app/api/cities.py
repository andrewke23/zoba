from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.functions import ST_Centroid, ST_X, ST_Y

from app.core.database import get_session
from app.models.entities import City
from app.schemas.cities import CityRead

router = APIRouter(prefix="/cities")


@router.get("", response_model=list[CityRead])
async def list_cities(session: AsyncSession = Depends(get_session)) -> list[CityRead]:
    """Catalog of pipeline cities the user can plan a trip in.

    The frontend draws and places home bases against a map center, so the
    bounding box is reduced to its centroid here.
    """
    rows = (
        await session.execute(
            select(
                City.city_id,
                City.name,
                ST_X(ST_Centroid(City.bbox)),
                ST_Y(ST_Centroid(City.bbox)),
                City.timezone,
            ).order_by(City.name)
        )
    ).all()
    return [
        CityRead(city_id=city_id, name=name, center=(lng, lat), timezone=timezone)
        for city_id, name, lng, lat, timezone in rows
    ]
