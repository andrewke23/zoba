from pydantic import BaseModel


class CityRead(BaseModel):
    city_id: str
    name: str
    # [lng, lat] centroid of the city bounding box, per the frontend map contract.
    center: tuple[float, float]
    timezone: str
