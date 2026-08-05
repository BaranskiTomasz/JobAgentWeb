from fastapi import APIRouter, Depends

import embeddings_repo
from db import get_db
from deps import get_current_user
from models import EmbeddingBatchUpsert, EmbeddingSimilarityRequest, EmbeddingVectorsRequest

router = APIRouter(prefix="/api/embeddings", tags=["embeddings"])


@router.get("/ids")
def indexed_ids(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return {"job_ids": list(embeddings_repo.get_indexed_ids(conn, user["id"]))}


@router.get("/unindexed")
def unindexed(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return embeddings_repo.get_unindexed(conn, user["id"])


@router.get("/all-indexed")
def all_indexed(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return embeddings_repo.get_all_indexed(conn, user["id"])


@router.post("")
def upsert(body: EmbeddingBatchUpsert, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    n = embeddings_repo.upsert_many(conn, [item.model_dump() for item in body.items])
    return {"indexed": n}


@router.post("/vectors")
def vectors(body: EmbeddingVectorsRequest, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return embeddings_repo.get_vectors(conn, user["id"], body.job_ids)


@router.post("/similarity")
def similarity(body: EmbeddingSimilarityRequest, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return embeddings_repo.score_by_similarity(conn, user["id"], body.ideal, body.job_ids)


@router.get("/decision-vectors")
def decision_vectors(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return embeddings_repo.get_decision_vectors(conn, user["id"])
