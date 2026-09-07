import uuid
import datetime
import json
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from backend.database import get_db
from backend.models import (
    AIConfiguration, AIConversation, AIMessage, AIAuditLog, User
)
from backend.ai_copilot import ai_provider

router = APIRouter(prefix="/api/ai", tags=["ai-assistant"])

def get_session_user(db: Session, x_user_id: Optional[str]) -> User:
    user_id = 1
    if x_user_id and x_user_id.isdigit():
        user_id = int(x_user_id)
    user = db.query(User).filter(User.id == user_id).first()
    return user or db.query(User).first()

class ChatRequestSchema(BaseModel):
    conversation_id: Optional[str] = None
    question: str
    ticket_context: Optional[Dict[str, Any]] = None

class QuickActionSchema(BaseModel):
    action: str # troubleshoot, summarize, similar_incidents, generate_work_note, draft_customer_response
    ticket_context: Dict[str, Any]
    user_notes: Optional[str] = None

class AIConfigUpdateSchema(BaseModel):
    is_enabled: bool = True
    assistant_name: str = "ITSM Support Copilot"
    welcome_message: str
    km_base_url: str
    api_endpoint: str
    auth_type: str = "Bearer"
    auth_token: Optional[str] = None
    km_im_token_endpoint: Optional[str] = None
    km_im_client_id: Optional[str] = None
    km_im_client_secret: Optional[str] = None
    km_im_token_json_path: str = "access_token"
    km_im_payload_template: str = '{"grant_type":"client_credentials","client_id":"{{client_id}}","client_secret":"{{client_secret}}"}'
    timeout_seconds: int = 30
    http_method: str = "POST"
    headers_template: str
    payload_template: str
    response_json_path: str
    allow_app_context: bool = True
    allow_project_context: bool = True
    allow_ticket_context: bool = True
    allow_history: bool = True
    pii_filtering: bool = True
    audit_enabled: bool = True

@router.get("/config")
def get_ai_configuration(db: Session = Depends(get_db)):
    cfg = db.query(AIConfiguration).first()
    if not cfg:
        cfg = AIConfiguration()
        db.add(cfg)
        db.commit()
    data = cfg.to_dict()
    if data.get("username"):
        data["username"] = "••••••••"
    if data.get("password"):
        data["password"] = "••••••••"
    if data.get("km_im_client_secret"):
        data["km_im_client_secret"] = "••••••••"
    return data

@router.put("/config")
def update_ai_configuration(payload: AIConfigUpdateSchema, db: Session = Depends(get_db)):
    cfg = db.query(AIConfiguration).first()
    if not cfg:
        cfg = AIConfiguration()
        db.add(cfg)

    cfg.is_enabled = payload.is_enabled
    cfg.assistant_name = payload.assistant_name
    cfg.welcome_message = payload.welcome_message
    cfg.km_base_url = payload.km_base_url
    cfg.api_endpoint = payload.api_endpoint
    cfg.auth_type = payload.auth_type
    if payload.auth_token is not None and payload.auth_token != "••••••••":
        cfg.auth_token = payload.auth_token
    cfg.km_im_token_endpoint = payload.km_im_token_endpoint
    cfg.km_im_client_id = payload.km_im_client_id
    if payload.km_im_client_secret is not None and payload.km_im_client_secret != "••••••••":
        cfg.km_im_client_secret = payload.km_im_client_secret
    cfg.km_im_token_json_path = payload.km_im_token_json_path
    cfg.km_im_payload_template = payload.km_im_payload_template
    cfg.timeout_seconds = payload.timeout_seconds
    cfg.http_method = payload.http_method
    cfg.headers_template = payload.headers_template
    cfg.payload_template = payload.payload_template
    cfg.response_json_path = payload.response_json_path
    cfg.allow_app_context = payload.allow_app_context
    cfg.allow_project_context = payload.allow_project_context
    cfg.allow_ticket_context = payload.allow_ticket_context
    cfg.allow_history = payload.allow_history
    cfg.pii_filtering = payload.pii_filtering
    cfg.audit_enabled = payload.audit_enabled

    db.commit()
    data = cfg.to_dict()
    if data.get("username"):
        data["username"] = "••••••••"
    if data.get("password"):
        data["password"] = "••••••••"
    if data.get("km_im_client_secret"):
        data["km_im_client_secret"] = "••••••••"
    return data

@router.post("/test-connection")
async def test_ai_connection(db: Session = Depends(get_db)):
    cfg = db.query(AIConfiguration).first()
    if not cfg:
        raise HTTPException(status_code=400, detail="AI Assistant not configured")
    result = await ai_provider.test_connection(cfg)
    return result

@router.get("/conversations")
def list_conversations(
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    convs = db.query(AIConversation).filter(
        AIConversation.user_id == current_user.id
    ).order_by(desc(AIConversation.updated_at)).limit(20).all()
    return [c.to_dict() for c in convs]

@router.get("/conversations/{conv_id}")
def get_conversation_history(
    conv_id: str,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    conv = db.query(AIConversation).filter(AIConversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    data = conv.to_dict()
    msgs = db.query(AIMessage).filter(AIMessage.conversation_id == conv_id).order_by(AIMessage.created_at.asc()).all()
    data["messages"] = [m.to_dict() for m in msgs]
    return data

@router.post("/chat")
async def send_chat_message(
    payload: ChatRequestSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    cfg = db.query(AIConfiguration).first()
    if not cfg:
        cfg = AIConfiguration()
        db.add(cfg)
        db.commit()

    if not cfg.is_enabled:
        raise HTTPException(status_code=503, detail="AI Knowledge Assistant is currently disabled by administrator")

    conv_id = payload.conversation_id
    conv = None
    if conv_id:
        conv = db.query(AIConversation).filter(AIConversation.id == conv_id).first()

    if not conv:
        conv_id = str(uuid.uuid4())
        short_title = payload.question[:45] + ("..." if len(payload.question) > 45 else "")
        conv = AIConversation(
            id=conv_id,
            user_id=current_user.id,
            title=short_title,
            ticket_number=payload.ticket_context.get("ticket_number") if payload.ticket_context else None
        )
        db.add(conv)
        db.flush()

    # Save User message
    user_msg = AIMessage(
        conversation_id=conv_id,
        role="user",
        content=payload.question
    )
    db.add(user_msg)
    db.flush()

    # Call AI Provider
    ai_resp = await ai_provider.chat(
        db=db,
        config=cfg,
        question=payload.question,
        conversation_id=conv_id,
        ticket_context=payload.ticket_context,
        user_info=current_user.to_dict()
    )

    # Save Assistant message
    assistant_msg = AIMessage(
        conversation_id=conv_id,
        role="assistant",
        content=ai_resp["content"],
        citations=json.dumps(ai_resp.get("citations", [])),
        token_usage=json.dumps({"tokens": ai_resp.get("token_count", 0)}),
        latency_ms=ai_resp.get("latency_ms", 0)
    )
    db.add(assistant_msg)
    conv.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {
        "conversation_id": conv_id,
        "message": assistant_msg.to_dict(),
        "citations": ai_resp.get("citations", [])
    }

@router.post("/quick-action")
async def execute_quick_action(
    payload: QuickActionSchema,
    x_user_id: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    current_user = get_session_user(db, x_user_id)
    cfg = db.query(AIConfiguration).first()
    ctx = payload.ticket_context or {}

    prompts = {
        "troubleshoot": f"How do I troubleshoot this incident: {ctx.get('short_description')}? Give me step-by-step diagnostic checks and commands.",
        "summarize": f"Summarize ticket {ctx.get('ticket_number')}: Problem, Impact, Investigation, Actions Taken, Current Status, and Next Steps.",
        "similar_incidents": f"Find similar past incidents for {ctx.get('application')} regarding {ctx.get('short_description')}.",
        "generate_work_note": f"Generate a professional internal work note based on: {payload.user_notes or ctx.get('short_description')}.",
        "draft_customer_response": f"Draft a courteous, non-technical customer response regarding ticket status for: {ctx.get('short_description')}."
    }

    question = prompts.get(payload.action, f"Assist with ticket {ctx.get('ticket_number')}")
    conv_id = str(uuid.uuid4())

    ai_resp = await ai_provider.chat(
        db=db,
        config=cfg,
        question=question,
        conversation_id=conv_id,
        ticket_context=ctx,
        user_info=current_user.to_dict()
    )

    return {
        "action": payload.action,
        "content": ai_resp["content"],
        "citations": ai_resp.get("citations", [])
    }

@router.get("/analytics")
def get_ai_analytics(db: Session = Depends(get_db)):
    """
    Returns AI usage metrics and dashboard analytics.
    """
    all_logs = db.query(AIAuditLog).all()
    total_queries = len(all_logs)

    today_start = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today_start.replace(day=1)

    today_queries = sum(1 for l in all_logs if getattr(l, "created_at", None) and l.created_at >= today_start)
    month_queries = sum(1 for l in all_logs if getattr(l, "created_at", None) and l.created_at >= month_start)

    success_count = sum(1 for l in all_logs if getattr(l, "success", False))
    failed_count = total_queries - success_count

    latencies = [l.response_time_ms for l in all_logs if getattr(l, "response_time_ms", None) is not None]
    avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0

    total_tokens = sum(getattr(l, "token_count", 0) or 0 for l in all_logs)

    recent_logs = sorted(all_logs, key=lambda x: getattr(x, "created_at", None) or datetime.datetime.min, reverse=True)[:15]

    return {
        "total_questions": total_queries,
        "questions_today": today_queries,
        "questions_this_month": month_queries,
        "successful_requests": success_count,
        "failed_requests": failed_count,
        "average_response_time_ms": round(float(avg_latency), 1),
        "total_tokens": int(total_tokens),
        "recent_audit_logs": [l.to_dict() for l in recent_logs]
    }
