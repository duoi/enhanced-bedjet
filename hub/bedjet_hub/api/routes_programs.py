"""REST routes for biorhythm program CRUD and activation."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


class StepRequest(BaseModel):
    mode: str
    temperatureC: float | None = None
    fanSpeedPercent: int | None = None
    durationMinutes: int = Field(ge=0)


class CreateProgramRequest(BaseModel):
    name: str
    steps: list[StepRequest] = []
    startTime: str | None = None
    days: list[int] | None = None


class UpdateProgramRequest(BaseModel):
    name: str | None = None
    steps: list[StepRequest] | None = None
    startTime: str | None = None
    days: list[int] | None = None


class ActivateRequest(BaseModel):
    startTime: str


def create_programs_router(db):
    """Build an APIRouter with CRUD and activation endpoints for programs."""
    r = APIRouter()

    @r.get("/programs")
    async def list_programs():
        return await db.list_programs()

    @r.post("/programs")
    async def create_program(req: CreateProgramRequest):
        return await db.create_program(
            name=req.name,
            steps=[s.model_dump() for s in req.steps],
            start_time_hhmm=req.startTime,
            days=req.days,
        )

    @r.post("/programs/stop")
    async def stop_program(request: Request):
        if hasattr(request.app.state, "scheduler"):
            await request.app.state.scheduler.stop_program()
        else:
            await db.delete_active_sequence()
        return {"ok": True}

    @r.get("/programs/active")
    async def get_active_program():
        a = await db.get_active_sequence()
        if not a:
            return None
        p = await db.get_program(a["program_id"])
        if not p:
            return None
        return {
            "programId": a["program_id"],
            "programName": p["name"],
            "startTime": a["start_time"],
            "currentStepIndex": a["current_step_index"],
            "startedAt": a["started_at"],
            "totalSteps": len(p["steps"]),
        }

    @r.get("/programs/{program_id}")
    async def get_program(program_id: str):
        p = await db.get_program(program_id)
        if not p:
            raise HTTPException(404, "Program not found")
        return p

    @r.put("/programs/{program_id}")
    async def update_program(program_id: str, req: UpdateProgramRequest):
        steps = [s.model_dump() for s in req.steps] if req.steps is not None else None
        u = await db.update_program(
            program_id,
            name=req.name,
            steps=steps,
            start_time_hhmm=req.startTime,
            days=req.days,
        )
        if not u:
            raise HTTPException(404, "Program not found")
        return u

    @r.delete("/programs/{program_id}")
    async def delete_program(program_id: str):
        if not await db.delete_program(program_id):
            raise HTTPException(404, "Program not found")
        return {"ok": True}

    @r.post("/programs/{program_id}/activate")
    async def activate_program(program_id: str, req: ActivateRequest, request: Request):
        p = await db.get_program(program_id)
        if not p:
            raise HTTPException(404, "Program not found")
        if not p["steps"]:
            raise HTTPException(400, "No steps")
        try:
            st = datetime.fromisoformat(req.startTime.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "Invalid startTime") from None

        try:
            if hasattr(request.app.state, "scheduler"):
                await request.app.state.scheduler.activate_program(p, st)
            else:
                now = datetime.now(st.tzinfo)
                delta = max(0, (now - st).total_seconds())
                elapsed = delta
                cs = 0
                for i, s in enumerate(p["steps"]):
                    ds = s["durationMinutes"] * 60
                    if ds == 0:
                        continue
                    if elapsed < ds:
                        cs = i
                        break
                    elapsed -= ds
                else:
                    if elapsed >= 0:
                        raise ValueError("Fully elapsed")

                await db.set_active_sequence(
                    program_id=program_id, start_time=req.startTime, current_step_index=cs, started_at=now.isoformat()
                )
        except ValueError as e:
            if str(e) == "Fully elapsed":
                raise HTTPException(400, "Program has fully elapsed") from None
            if str(e) == "No steps":
                raise HTTPException(400, "No steps") from None
            raise HTTPException(500, str(e)) from None

        return {"ok": True}

    return r
