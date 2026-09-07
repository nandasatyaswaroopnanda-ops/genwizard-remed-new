from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc
from typing import Optional, List
from pydantic import BaseModel

from backend.database import get_db
from backend.models import KnowledgeArticle, User
from backend.security import get_user_scopes

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

def get_session_user(db: Session, x_user_id: Optional[str]) -> User:
    user_id = 1
    if x_user_id and x_user_id.isdigit():
        user_id = int(x_user_id)
    return db.query(User).filter(User.id == user_id).first() or db.query(User).first()

class ArticleSchema(BaseModel):
    title: str
    category: str = "Troubleshooting"
    application_id: Optional[int] = None
    content: str
    status: str = "Published"

@router.get("")
def list_articles(
    category: Optional[str] = None,
    application_id: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(KnowledgeArticle).filter(KnowledgeArticle.status == "Published")
    if category:
        query = query.filter(KnowledgeArticle.category == category)
    if application_id:
        query = query.filter(KnowledgeArticle.application_id == application_id)
    if search:
        s = f"%{search}%"
        query = query.filter(
            or_(
                KnowledgeArticle.title.ilike(s),
                KnowledgeArticle.content.ilike(s),
                KnowledgeArticle.article_number.ilike(s)
            )
        )
    articles = query.order_by(desc(KnowledgeArticle.created_at)).all()
    return [a.to_dict() for a in articles]

@router.get("/suggested")
def get_suggested_articles(
    application_id: Optional[int] = None,
    query: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Returns AI / heuristic suggested knowledge base articles based on ticket input.
    """
    q = db.query(KnowledgeArticle).filter(KnowledgeArticle.status == "Published")
    if application_id:
        q = q.filter(KnowledgeArticle.application_id == application_id)
    if query:
        words = query.strip().split()
        for w in words[:3]:
            if len(w) > 3:
                q = q.filter(KnowledgeArticle.title.ilike(f"%{w}%"))
    results = q.limit(4).all()
    if not results:
        results = db.query(KnowledgeArticle).filter(KnowledgeArticle.status == "Published").limit(3).all()
    return [a.to_dict() for a in results]

@router.get("/{article_id_or_number}")
def get_article(article_id_or_number: str, db: Session = Depends(get_db)):
    if article_id_or_number.isdigit():
        art = db.query(KnowledgeArticle).filter(KnowledgeArticle.id == int(article_id_or_number)).first()
    else:
        art = db.query(KnowledgeArticle).filter(KnowledgeArticle.article_number == article_id_or_number).first()
    if not art:
        raise HTTPException(status_code=404, detail="Knowledge article not found")
    return art.to_dict()

@router.post("")
def create_article(
    payload: ArticleSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """Support members, group managers, and administrators can create knowledge articles. End users are restricted."""
    current_user = get_session_user(db, x_user_id)
    scopes = get_user_scopes(current_user, db)
    if scopes["is_end_user"] or (current_user.role in ("employee", "im_saml") and not scopes["is_support_member"] and not scopes["is_global_admin"]):
        raise HTTPException(status_code=403, detail="End users have read-only access to the Knowledge Base and cannot create articles")

    last_art = db.query(KnowledgeArticle).order_by(desc(KnowledgeArticle.id)).first()
    next_seq = (last_art.id + 1001) if last_art else 1001
    art_num = f"KB{next_seq:07d}"

    art = KnowledgeArticle(
        article_number=art_num,
        title=payload.title,
        category=payload.category,
        application_id=payload.application_id,
        content=payload.content,
        author_id=current_user.id,
        status=payload.status
    )
    db.add(art)
    db.commit()
    db.refresh(art)
    return art.to_dict()

@router.put("/{article_id}")
def update_article(
    article_id: int,
    payload: ArticleSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """Support members, group managers, and administrators can update knowledge articles. End users are restricted."""
    current_user = get_session_user(db, x_user_id)
    scopes = get_user_scopes(current_user, db)
    if scopes["is_end_user"] or (current_user.role in ("employee", "im_saml") and not scopes["is_support_member"] and not scopes["is_global_admin"]):
        raise HTTPException(status_code=403, detail="End users have read-only access to the Knowledge Base and cannot update articles")

    article = db.query(KnowledgeArticle).filter(KnowledgeArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Knowledge article not found")
    article.title = payload.title
    article.category = payload.category
    article.application_id = payload.application_id
    article.content = payload.content
    article.status = payload.status
    db.commit()
    db.refresh(article)
    return article.to_dict()

@router.delete("/{article_id}")
def delete_article(
    article_id: int,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """Support team and admins can delete articles. End users are restricted."""
    current_user = get_session_user(db, x_user_id)
    scopes = get_user_scopes(current_user, db)
    if scopes["is_end_user"] or (current_user.role in ("employee", "im_saml") and not scopes["is_support_member"] and not scopes["is_global_admin"]):
        raise HTTPException(status_code=403, detail="Support team or administrator role required to delete articles")

    article = db.query(KnowledgeArticle).filter(KnowledgeArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Knowledge article not found")
    db.delete(article)
    db.commit()
    return {"message": "Knowledge article deleted"}
