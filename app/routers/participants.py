import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Participant
from ..schemas import ParticipantCreate, ParticipantResponse


router = APIRouter(prefix="/participants", tags=["participants"])


@router.post("", response_model=ParticipantResponse, status_code=201)
def create_participant(
    payload: ParticipantCreate, db: Session = Depends(get_db)
) -> Participant:
    participant = Participant(name=payload.name, email=payload.email)
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


@router.get("", response_model=list[ParticipantResponse])
def list_participants(db: Session = Depends(get_db)) -> list[Participant]:
    return list(db.scalars(select(Participant).order_by(Participant.name)).all())


@router.get("/{participant_id}", response_model=ParticipantResponse)
def get_participant(participant_id: int, db: Session = Depends(get_db)) -> Participant:
    participant = db.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    return participant


@router.patch("/{participant_id}", response_model=ParticipantResponse)
def update_participant(
    participant_id: int, payload: ParticipantCreate, db: Session = Depends(get_db)
) -> Participant:
    participant = db.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    participant.name = payload.name
    participant.email = payload.email
    db.commit()
    db.refresh(participant)
    return participant


@router.delete("/{participant_id}", status_code=204)
def delete_participant(participant_id: int, db: Session = Depends(get_db)) -> None:
    participant = db.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    db.delete(participant)
    db.commit()
