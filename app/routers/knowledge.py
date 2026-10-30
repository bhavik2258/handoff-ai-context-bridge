import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import KnowledgeDoc
from ..schemas import KnowledgeDocCreate, KnowledgeDocResponse


router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _doc_response(doc: KnowledgeDoc) -> KnowledgeDocResponse:
    return KnowledgeDocResponse(
        id=doc.id,
        title=doc.title,
        content=doc.content or "",
        doc_type=doc.doc_type,
        tags=json.loads(doc.tags or "[]"),
    )


@router.post("", response_model=KnowledgeDocResponse, status_code=201)
def create_document(
    payload: KnowledgeDocCreate, db: Session = Depends(get_db)
) -> KnowledgeDocResponse:
    doc = KnowledgeDoc(
        title=payload.title,
        content=payload.content,
        doc_type=payload.doc_type,
        tags=json.dumps(payload.tags),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _doc_response(doc)


@router.get("", response_model=list[KnowledgeDocResponse])
def list_documents(db: Session = Depends(get_db)) -> list[KnowledgeDocResponse]:
    docs = db.scalars(select(KnowledgeDoc).order_by(KnowledgeDoc.id)).all()
    return [_doc_response(doc) for doc in docs]


@router.get("/{doc_id}", response_model=KnowledgeDocResponse)
def get_document(doc_id: int, db: Session = Depends(get_db)) -> KnowledgeDocResponse:
    doc = db.get(KnowledgeDoc, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return _doc_response(doc)
