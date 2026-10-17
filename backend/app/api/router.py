from fastapi import APIRouter

from app.api import auth, cost_estimates, expenses, trips

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(trips.router, tags=["trips"])
api_router.include_router(expenses.router, tags=["expenses"])
api_router.include_router(cost_estimates.router, tags=["cost estimates"])
