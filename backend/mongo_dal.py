"""Genwizard ITSM — High-Performance Native MongoDB Data Access Layer (DAL).
Provides 100% MongoDB document persistence for all platform entities:
Users, Incidents, ServiceRequests, ChangeRequests, Applications, Projects,
AssignmentGroups, RoutingRules, SLAPolicies, Calendars, Taxonomy, and SSO/Identity.
Zero SQLite and Zero PostgreSQL required.
"""
import os
import re
import copy
import logging
import datetime
from typing import Any, Dict, List, Optional, Tuple, Type, Union
from pymongo import MongoClient, ReturnDocument, ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

logger = logging.getLogger("mongo_dal")

def _get_consul_raw(consul_addr: str, key: str, headers: dict) -> str:
    """Retrieve raw string from Consul KV store across direct docker exec and candidate endpoints."""
    # 1. Direct Docker CLI inspection if docker command is available
    try:
        import shutil, subprocess
        if shutil.which("docker"):
            p = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=2
            )
            if p.returncode == 0:
                consul_cntrs = [c.strip() for c in p.stdout.splitlines() if "consul" in c.lower()]
                for cntr in consul_cntrs:
                    d_res = subprocess.run(
                        ["docker", "exec", cntr, "consul", "kv", "get", key],
                        capture_output=True, text=True, timeout=2
                    )
                    if d_res.returncode == 0 and d_res.stdout.strip():
                        return d_res.stdout.strip()
    except Exception:
        pass

    # 2. HTTP candidate endpoints
    candidate_addrs = [
        consul_addr,
        "http://consul:8500",
        "http://host.docker.internal:8500",
        "http://127.0.0.1:8500",
        "http://localhost:8500"
    ]
    for c_addr in candidate_addrs:
        if not c_addr:
            continue
        try:
            import requests
            r = requests.get(f"{c_addr.rstrip('/')}/v1/kv/{key}", params={"raw": ""}, headers=headers, timeout=2)
            if r.status_code == 200:
                return r.text.strip()
        except Exception:
            pass
    return ""

def resolve_platform_dns() -> str:
    """
    Resolves the base platform DNS / URL from:
    1. Consul key: configuration/aaam-atr-v3-gateway/dns
    2. Environment variables: PLATFORM_DNS, APP_URL, SERVER_NAME
    3. Default fallback
    """
    dns = os.getenv("PLATFORM_DNS", "").strip() or os.getenv("APP_URL", "").strip()
    if dns:
        return dns.rstrip("/")
    consul_addr = os.getenv("CONSUL_HTTP_ADDR", "").rstrip("/")
    if consul_addr:
        consul_token = os.getenv("CONSUL_HTTP_TOKEN", "")
        hdrs = {"X-Consul-Token": consul_token} if consul_token else {}
        val = _get_consul_raw(consul_addr, "configuration/aaam-atr-v3-gateway/dns", hdrs)
        if val:
            if not val.startswith("http://") and not val.startswith("https://"):
                val = f"https://{val}"
            return val.rstrip("/")
    return "http://localhost:8080"

def resolve_mongo_config() -> Tuple[str, str]:
    """
    Resolves MongoDB connection URL and database name from:
    1. MONGO_URL environment variable
    2. Spring Cloud Consul keys:
       - configuration/aaam-atr-v3-gateway/spring.data.mongodb.host
       - configuration/aaam-atr-v3-gateway/spring.data.mongodb.username
       - configuration/aaam-atr-v3-gateway/spring.data.mongodb.password
       - configuration/aaam-atr-v3-gateway/spring.data.mongodb.authentication_database
    3. Consul Key-Value store (CONSUL_MONGO_KEY or standard bootstrap paths)
    4. Default credentials (username 'atr' or 'mongo-atr' at host 'atr-mongo:27017')
    """
    mongo_url = os.getenv("MONGO_URL", "").strip()
    mongo_db_name = os.getenv("MONGO_DATABASE", "nexus_itsm").strip()
    if mongo_url:
        return mongo_url, mongo_db_name

    mongo_pwd = os.getenv("MONGO_PASSWORD", "").strip()
    if mongo_pwd:
        mongo_user = os.getenv("MONGO_USERNAME", os.getenv("MONGO_USER", "atr")).strip()
        mongo_host = os.getenv("MONGO_HOST", "atr-mongo").strip()
        mongo_port = os.getenv("MONGO_PORT", "27017").strip()
        mongo_auth_db = os.getenv("MONGO_AUTH_SOURCE", "admin").strip()
        return f"mongodb://{mongo_user}:{mongo_pwd}@{mongo_host}:{mongo_port}/{mongo_db_name}?authSource={mongo_auth_db}", mongo_db_name

    # Check Consul KV if configured
    consul_addr = os.getenv("CONSUL_HTTP_ADDR", "").rstrip("/")
    if consul_addr:
        try:
            import requests
            consul_token = os.getenv("CONSUL_HTTP_TOKEN", "")
            hdrs = {"X-Consul-Token": consul_token} if consul_token else {}

            # 1. Check specific Spring Cloud Consul keys for MongoDB
            spring_pwd = _get_consul_raw(consul_addr, "configuration/aaam-atr-v3-gateway/spring.data.mongodb.password", hdrs)
            if spring_pwd:
                spring_host = _get_consul_raw(consul_addr, "configuration/aaam-atr-v3-gateway/spring.data.mongodb.host", hdrs) or "atr-mongo"
                spring_user = _get_consul_raw(consul_addr, "configuration/aaam-atr-v3-gateway/spring.data.mongodb.username", hdrs) or "atr"
                spring_auth_db = _get_consul_raw(consul_addr, "configuration/aaam-atr-v3-gateway/spring.data.mongodb.authentication_database", hdrs) or "admin"

                host = spring_host
                port = 27017
                if ":" in host:
                    parts = host.split(":")
                    host = parts[0]
                    try:
                        port = int(parts[1])
                    except ValueError:
                        pass
                database = mongo_db_name
                mongo_url = f"mongodb://{spring_user}:{spring_pwd}@{host}:{port}/{database}?authSource={spring_auth_db}"
                logger.info("Resolved MongoDB connection from Consul Spring keys (host=%s, user=%s, authDb=%s)", host, spring_user, spring_auth_db)
                return mongo_url, database

            # 2. Check candidate composite JSON keys
            candidate_keys = [
                os.getenv("CONSUL_MONGO_KEY", "").strip(),
                "nexus-itsm/bootstrap/mongo",
                "nexus-itsm/mongo",
                "atr-mongo/credentials",
                "atr-mongo",
                "mongo/credentials",
                "bootstrap/mongo"
            ]
            for key in candidate_keys:
                if not key:
                    continue
                r = requests.get(f"{consul_addr}/v1/kv/{key}", params={"raw": ""}, headers=hdrs, timeout=3)
                if r.status_code == 200:
                    data = None
                    try:
                        data = r.json()
                    except Exception:
                        data = r.text.strip()
                    if isinstance(data, dict):
                        user = data.get("username") or data.get("user") or "atr"
                        pwd = data.get("password") or data.get("pass") or ""
                        host = data.get("host") or data.get("hostname") or "atr-mongo"
                        port = data.get("port") or 27017
                        database = data.get("database") or data.get("db") or mongo_db_name
                        auth_src = data.get("authSource") or "admin"
                        if pwd:
                            mongo_url = f"mongodb://{user}:{pwd}@{host}:{port}/{database}?authSource={auth_src}"
                            return mongo_url, database
                    elif isinstance(data, str) and data.startswith("mongodb://"):
                        return data, mongo_db_name
        except Exception as e:
            logger.debug("Could not resolve mongo credentials from Consul: %s", e)

    # Fallback to atr-mongo defaults if MONGO_PASSWORD is provided
    default_pass = os.getenv("MONGO_PASSWORD", "")
    if default_pass:
        return f"mongodb://atr:{default_pass}@atr-mongo:27017/{mongo_db_name}?authSource=admin", mongo_db_name

    return mongo_url, mongo_db_name

MONGO_URL, MONGO_DATABASE = resolve_mongo_config()


# ── In-Memory Document Store Fallback (for offline unit tests) ──

class InMemoryCursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs
        self._sort_key = None
        self._limit_n = None
        self._skip_n = 0

    def sort(self, key_or_list, direction=None):
        if isinstance(key_or_list, list):
            self._sort_key = key_or_list
        elif isinstance(key_or_list, str):
            self._sort_key = [(key_or_list, direction or ASCENDING)]
        return self

    def limit(self, n: int):
        self._limit_n = n
        return self

    def skip(self, n: int):
        self._skip_n = n
        return self

    def _execute(self) -> List[Dict[str, Any]]:
        docs = list(self._docs)
        if self._sort_key:
            for field, direction in reversed(self._sort_key):
                reverse = (direction in (-1, DESCENDING))
                docs.sort(
                    key=lambda d: (d.get(field) is None, d.get(field)),
                    reverse=reverse
                )
        if self._skip_n:
            docs = docs[self._skip_n:]
        if self._limit_n is not None:
            docs = docs[:self._limit_n]
        return docs

    def __iter__(self):
        return iter(self._execute())

    def __len__(self):
        return len(self._execute())


class InMemoryCollection:
    def __init__(self, name: str):
        self.name = name
        self._data: Dict[Any, Dict[str, Any]] = {}

    def _matches(self, doc: Dict[str, Any], filter_dict: Dict[str, Any]) -> bool:
        if not filter_dict:
            return True
        for k, v in filter_dict.items():
            if k == "$or":
                if not any(self._matches(doc, sf) for sf in v):
                    return False
            elif k == "$and":
                if not all(self._matches(doc, sf) for sf in v):
                    return False
            elif k == "$exists":
                continue
            else:
                doc_val = doc.get(k)
                if isinstance(v, dict):
                    for op, target in v.items():
                        if op == "$eq":
                            if target is None:
                                if doc_val is not None:
                                    return False
                            elif doc_val != target:
                                return False
                        elif op == "$ne":
                            if target is None:
                                if doc_val is None:
                                    return False
                            elif doc_val == target:
                                return False
                        elif op == "$gt" and not (doc_val is not None and doc_val > target):
                            return False
                        elif op == "$gte" and not (doc_val is not None and doc_val >= target):
                            return False
                        elif op == "$lt" and not (doc_val is not None and doc_val < target):
                            return False
                        elif op == "$lte" and not (doc_val is not None and doc_val <= target):
                            return False
                        elif op == "$in" and doc_val not in target:
                            return False
                        elif op == "$nin" and doc_val in target:
                            return False
                        elif op == "$exists":
                            if (k in doc) != target:
                                return False
                        elif op == "$regex":
                            flags = re.IGNORECASE if v.get("$options") == "i" else 0
                            if not re.search(target, str(doc_val or ""), flags):
                                return False
                else:
                    if v is None:
                        if doc_val is not None:
                            return False
                    else:
                        if doc_val != v:
                            return False
        return True

    def find(self, filter_dict: Optional[Dict[str, Any]] = None) -> InMemoryCursor:
        filter_dict = filter_dict or {}
        matches = [copy.deepcopy(doc) for doc in self._data.values() if self._matches(doc, filter_dict)]
        return InMemoryCursor(matches)

    def find_one(self, filter_dict: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        cursor = self.find(filter_dict)
        docs = cursor._execute()
        return copy.deepcopy(docs[0]) if docs else None

    def insert_one(self, doc: Dict[str, Any]):
        doc_copy = copy.deepcopy(doc)
        _id = doc_copy.get("_id") or doc_copy.get("id")
        self._data[_id] = doc_copy

    def replace_one(self, filter_dict: Dict[str, Any], doc: Dict[str, Any], upsert: bool = False):
        doc_copy = copy.deepcopy(doc)
        target_id = None
        for _id, existing in self._data.items():
            if self._matches(existing, filter_dict):
                target_id = _id
                break
        if target_id is not None:
            self._data[target_id] = doc_copy
        elif upsert:
            _id = doc_copy.get("_id") or doc_copy.get("id") or filter_dict.get("_id") or filter_dict.get("id")
            doc_copy["_id"] = _id
            self._data[_id] = doc_copy

    def update_one(self, filter_dict: Dict[str, Any], update: Dict[str, Any], upsert: bool = False):
        target = None
        for doc in self._data.values():
            if self._matches(doc, filter_dict):
                target = doc
                break
        if not target and upsert:
            target = dict(filter_dict)
            _id = target.get("_id") or target.get("id") or len(self._data) + 1
            target["_id"] = _id
            self._data[_id] = target
        if target:
            if "$set" in update:
                for k, v in update["$set"].items():
                    target[k] = v
            if "$inc" in update:
                for k, v in update["$inc"].items():
                    target[k] = target.get(k, 0) + v

    def delete_one(self, filter_dict: Dict[str, Any]):
        for _id, doc in list(self._data.items()):
            if self._matches(doc, filter_dict):
                del self._data[_id]
                break

    def delete_many(self, filter_dict: Dict[str, Any]):
        for _id, doc in list(self._data.items()):
            if self._matches(doc, filter_dict):
                del self._data[_id]

    def count_documents(self, filter_dict: Optional[Dict[str, Any]] = None) -> int:
        filter_dict = filter_dict or {}
        return sum(1 for doc in self._data.values() if self._matches(doc, filter_dict))

    def find_one_and_update(self, filter_dict: Dict[str, Any], update: Dict[str, Any], upsert: bool = False, return_document=None) -> Dict[str, Any]:
        target = None
        for doc in self._data.values():
            if self._matches(doc, filter_dict):
                target = doc
                break
        if not target and upsert:
            target = dict(filter_dict)
            _id = target.get("_id") or target.get("id")
            self._data[_id] = target
        if target:
            if "$inc" in update:
                for k, v in update["$inc"].items():
                    target[k] = target.get(k, 0) + v
            if "$set" in update:
                for k, v in update["$set"].items():
                    target[k] = v
        return copy.deepcopy(target)

    def drop(self):
        self._data.clear()


class InMemoryDatabase:
    def __init__(self, name: str):
        self.name = name
        self._collections: Dict[str, InMemoryCollection] = {}

    def __getitem__(self, item: str) -> InMemoryCollection:
        if item not in self._collections:
            self._collections[item] = InMemoryCollection(item)
        return self._collections[item]

    def __getattr__(self, item: str) -> InMemoryCollection:
        return self[item]

    def command(self, cmd: str) -> Dict[str, Any]:
        return {"ok": 1.0}


# ── Database Initialization ──

_mongo_client: Optional[Any] = None
_mongo_database: Optional[Any] = None

def init_mongo() -> Tuple[Any, Any]:
    global _mongo_client, _mongo_database
    if _mongo_database is not None:
        return _mongo_client, _mongo_database

    if MONGO_URL:
        try:
            client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000)
            client.admin.command("ping")
            db = client[MONGO_DATABASE]
            _mongo_client = client
            _mongo_database = db
            logger.info("Connected to native MongoDB cluster: %s (db: %s)", MONGO_URL.split("@")[-1], MONGO_DATABASE)
            return _mongo_client, _mongo_database
        except Exception as e:
            logger.warning("MongoDB at %s unreachable (%s). Using fast in-memory document engine.", MONGO_URL, e)

    # In-memory document database
    logger.info("Initializing in-memory native Mongo document datastore.")
    _mongo_database = InMemoryDatabase(MONGO_DATABASE)
    _mongo_client = None
    return _mongo_client, _mongo_database

mongo_client, mongo_db = init_mongo()

def get_mongo_db() -> Any:
    global mongo_db
    if mongo_db is None:
        _, mongo_db = init_mongo()
    return mongo_db


# ── Auto-Increment Counter Helper ──

def get_next_id(collection_name: str) -> int:
    db = get_mongo_db()
    max_id = 0
    try:
        cursor = db[collection_name].find().sort("id", DESCENDING).limit(1)
        top_docs = list(cursor)
        if top_docs and isinstance(top_docs[0].get("id"), int):
            max_id = top_docs[0]["id"]
    except Exception:
        pass

    res = db["counters"].find_one_and_update(
        {"_id": collection_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    current_seq = int(res.get("seq", 1))
    if max_id >= current_seq:
        current_seq = max_id + 1
        db["counters"].update_one({"_id": collection_name}, {"$set": {"seq": current_seq}})
    return current_seq


# ── SQLAlchemy Expression -> MongoDB Filter Translator ──

def expr_to_mongo(criterion: Any) -> Dict[str, Any]:
    if criterion is None:
        return {}
    if isinstance(criterion, dict):
        return criterion
    if isinstance(criterion, bool):
        return {} if criterion else {"_id": {"$exists": False}}

    # Binary expressions (e.g. Model.field == val)
    if hasattr(criterion, "left") and hasattr(criterion, "operator"):
        left_attr = criterion.left
        key = getattr(left_attr, "key", getattr(left_attr, "name", str(left_attr)))
        
        # Extract target value
        right = getattr(criterion, "right", None)
        val = getattr(right, "value", right)
        if hasattr(val, "element"):
            val = getattr(val, "element", val)
        if type(val).__name__ in ("Null", "NullType") or str(val) == "NULL":
            val = None
        elif type(val).__name__ in ("True_",):
            val = True
        elif type(val).__name__ in ("False_",):
            val = False

        op_name = getattr(criterion.operator, "__name__", str(criterion.operator))
        
        if op_name in ("eq", "is_"):
            return {key: val}
        elif op_name in ("ne", "is_not"):
            return {key: {"$ne": val}}
        elif op_name == "gt":
            return {key: {"$gt": val}}
        elif op_name == "ge":
            return {key: {"$gte": val}}
        elif op_name == "lt":
            return {key: {"$lt": val}}
        elif op_name == "le":
            return {key: {"$lte": val}}
        elif op_name == "in_op":
            vals = list(val) if isinstance(val, (list, tuple, set)) else [val]
            return {key: {"$in": vals}}
        elif op_name == "not_in_op":
            vals = list(val) if isinstance(val, (list, tuple, set)) else [val]
            return {key: {"$nin": vals}}
        elif op_name in ("like_op", "ilike_op"):
            val_str = str(val).strip("%")
            return {key: {"$regex": val_str, "$options": "i"}}
        return {key: val}

    # Boolean conjunctions (or_ / and_)
    if hasattr(criterion, "clauses") and hasattr(criterion, "operator"):
        op_name = getattr(criterion.operator, "__name__", str(criterion.operator))
        sub_filters = [expr_to_mongo(cl) for cl in criterion.clauses]
        if op_name == "or_":
            return {"$or": sub_filters}
        elif op_name == "and_":
            return {"$and": sub_filters}

    # Unary or boolean column expression (e.g. Model.field or not_(Model.field))
    if hasattr(criterion, "element") and not hasattr(criterion, "clauses") and not hasattr(criterion, "left"):
        elem = criterion.element
        modifier = getattr(criterion, "modifier", None)
        mod_name = getattr(modifier, "__name__", str(modifier)) if modifier else ""
        elem_key = getattr(elem, "key", getattr(elem, "name", str(elem)))
        if "not" in mod_name.lower():
            return {elem_key: False}
        return {elem_key: True}

    if hasattr(criterion, "key") or hasattr(criterion, "name"):
        key = getattr(criterion, "key", getattr(criterion, "name", str(criterion)))
        return {key: True}

    return {}


def merge_filters(f1: Dict[str, Any], f2: Dict[str, Any]) -> Dict[str, Any]:
    if not f1:
        return dict(f2)
    if not f2:
        return dict(f1)
    merged = dict(f1)
    for k, v in f2.items():
        if k not in merged:
            merged[k] = v
        else:
            # If both are sub-operator dicts, e.g. {"$gte": ...} and {"$lte": ...}
            if isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k] = {**merged[k], **v}
            else:
                # Merge into $and
                if "$and" not in merged:
                    merged = {"$and": [dict(f1), {k: v}]}
                else:
                    merged["$and"].append({k: v})
    return merged


# ── Model <-> Document Hydration ──

def doc_to_model(model_cls: Type[Any], doc: Optional[Dict[str, Any]], session: Optional['MongoSession'] = None) -> Optional[Any]:
    if not doc:
        return None

    doc_id = doc.get("_id") or doc.get("id")
    if session and doc_id is not None:
        key = (model_cls.__name__, doc_id)
        if key in session._identity_map:
            return session._identity_map[key]

    init_kwargs = {}
    if hasattr(model_cls, "__table__"):
        for col in model_cls.__table__.columns:
            if col.name in doc:
                init_kwargs[col.name] = doc[col.name]
            elif col.default is not None:
                arg = col.default.arg
                init_kwargs[col.name] = arg(None) if callable(arg) else arg

    # Create model instance
    try:
        instance = model_cls(**init_kwargs)
    except Exception:
        instance = model_cls()
        for k, v in init_kwargs.items():
            setattr(instance, k, v)

    if getattr(instance, "id", None) is None:
        instance.id = doc_id

    if session and instance.id is not None:
        session._identity_map[(model_cls.__name__, instance.id)] = instance

    # Hydrate relationships if session is available
    if session:
        hydrate_relationships(instance, session)
        session._queried.append(instance)

    return instance


def model_to_doc(instance: Any) -> Dict[str, Any]:
    doc = {}
    model_cls = instance.__class__
    if hasattr(model_cls, "__table__"):
        for col in model_cls.__table__.columns:
            val = getattr(instance, col.name, None)
            if val is None and col.default is not None:
                arg = col.default.arg
                val = arg(None) if callable(arg) else arg
                try:
                    setattr(instance, col.name, val)
                except Exception:
                    pass
            doc[col.name] = val
    else:
        for k, v in instance.__dict__.items():
            if not k.startswith("_"):
                doc[k] = v

    doc_id = getattr(instance, "id", None)
    if doc_id is not None:
        doc["_id"] = doc_id
        doc["id"] = doc_id
    return doc


def hydrate_relationships(instance: Any, session: 'MongoSession', _visited: Optional[set] = None):
    """Populate relationships commonly accessed by platform engines and route endpoints."""
    if instance is None:
        return
    if _visited is None:
        _visited = set()
    inst_key = (instance.__class__.__name__, getattr(instance, "id", id(instance)))
    if inst_key in _visited:
        return
    _visited.add(inst_key)

    cls_name = instance.__class__.__name__

    if cls_name == "User":
        from backend.models import GroupMember, UserCustomGroup, Notification
        # Memberships
        members = session.query(GroupMember).filter_by(user_id=instance.id).all()
        instance.memberships = members
        # Custom groups
        cgroups = session.query(UserCustomGroup).filter_by(user_id=instance.id).all()
        for cg in cgroups:
            hydrate_relationships(cg, session, _visited)
        instance.custom_groups = cgroups
        # Notifications
        instance.notifications = session.query(Notification).filter_by(recipient_id=instance.id).all()

    elif cls_name == "UserCustomGroup":
        from backend.models import CustomGroup
        instance.custom_group = session.query(CustomGroup).filter_by(id=instance.custom_group_id).first()

    elif cls_name == "ADGroupMapping":
        from backend.models import CustomGroup
        if instance.custom_group_id:
            instance.custom_group = session.query(CustomGroup).filter_by(id=instance.custom_group_id).first()
        else:
            instance.custom_group = None

    elif cls_name in ("Incident", "ServiceRequest", "ChangeRequest"):
        from backend.models import (
            SLAInstance, TicketComment, TicketWorkNote, Approval,
            User, Application, Project, AssignmentGroup
        )
        ticket_type = "Incident" if cls_name == "Incident" else ("Service Request" if cls_name == "ServiceRequest" else "Change Request")
        instance.sla_instances = session.query(SLAInstance).filter_by(ticket_id=instance.id, ticket_type=ticket_type).all()
        instance.comments = session.query(TicketComment).filter_by(ticket_id=instance.id, ticket_type=ticket_type).order_by(TicketComment.created_at.asc()).all()
        instance.work_notes = session.query(TicketWorkNote).filter_by(ticket_id=instance.id, ticket_type=ticket_type).order_by(TicketWorkNote.created_at.asc()).all()
        if cls_name == "ChangeRequest":
            instance.approvals = session.query(Approval).filter_by(change_request_id=instance.id).all()

        # Foreign-key entity relationships
        if getattr(instance, "caller_id", None):
            instance.caller = session.query(User).filter_by(id=instance.caller_id).first()
        if getattr(instance, "requested_for_id", None):
            instance.requested_for = session.query(User).filter_by(id=instance.requested_for_id).first()
        if getattr(instance, "requested_by_id", None):
            instance.requested_by = session.query(User).filter_by(id=instance.requested_by_id).first()
        if getattr(instance, "opened_by_id", None):
            instance.opened_by = session.query(User).filter_by(id=instance.opened_by_id).first()
        if getattr(instance, "assigned_to_id", None):
            instance.assigned_to = session.query(User).filter_by(id=instance.assigned_to_id).first()
        if getattr(instance, "application_id", None):
            instance.application = session.query(Application).filter_by(id=instance.application_id).first()
        if getattr(instance, "project_id", None):
            instance.project = session.query(Project).filter_by(id=instance.project_id).first()
        if getattr(instance, "assignment_group_id", None):
            instance.assignment_group = session.query(AssignmentGroup).filter_by(id=instance.assignment_group_id).first()

    elif cls_name == "TicketComment":
        from backend.models import User
        if getattr(instance, "user_id", None):
            instance.user = session.query(User).filter_by(id=instance.user_id).first()

    elif cls_name == "TicketWorkNote":
        from backend.models import User
        if getattr(instance, "user_id", None):
            instance.user = session.query(User).filter_by(id=instance.user_id).first()

    elif cls_name == "Approval":
        from backend.models import User
        if getattr(instance, "approver_id", None):
            instance.approver = session.query(User).filter_by(id=instance.approver_id).first()

    elif cls_name == "KnowledgeArticle":
        from backend.models import User, Application
        if getattr(instance, "application_id", None):
            instance.application = session.query(Application).filter_by(id=instance.application_id).first()
        if getattr(instance, "author_id", None):
            instance.author = session.query(User).filter_by(id=instance.author_id).first()

    elif cls_name == "AssignmentGroup":
        from backend.models import GroupMember, GroupDistributionList
        instance.members = session.query(GroupMember).filter_by(group_id=instance.id).all()
        instance.distribution_lists = session.query(GroupDistributionList).filter_by(group_id=instance.id).all()

    elif cls_name == "SLAInstance":
        from backend.models import SLAPolicy
        if getattr(instance, "sla_policy_id", None):
            instance.sla_policy = session.query(SLAPolicy).filter_by(id=instance.sla_policy_id).first()

    elif cls_name == "SLAPolicy":
        from backend.models import BusinessCalendar
        if getattr(instance, "business_calendar_id", None):
            instance.business_calendar = session.query(BusinessCalendar).filter_by(id=instance.business_calendar_id).first()

    elif cls_name == "Application":
        from backend.models import AssignmentGroup, SLAPolicy, Project
        if getattr(instance, "default_assignment_group_id", None):
            instance.default_assignment_group = session.query(AssignmentGroup).filter_by(id=instance.default_assignment_group_id).first()
        if getattr(instance, "default_sla_policy_id", None):
            instance.default_sla_policy = session.query(SLAPolicy).filter_by(id=instance.default_sla_policy_id).first()
        if getattr(instance, "project_id", None):
            instance.project = session.query(Project).filter_by(id=instance.project_id).first()

    elif cls_name == "Project":
        from backend.models import AssignmentGroup, SLAPolicy, Application
        if getattr(instance, "default_assignment_group_id", None):
            instance.default_assignment_group = session.query(AssignmentGroup).filter_by(id=instance.default_assignment_group_id).first()
        if getattr(instance, "l2_assignment_group_id", None):
            instance.l2_assignment_group = session.query(AssignmentGroup).filter_by(id=instance.l2_assignment_group_id).first()
        if getattr(instance, "l3_assignment_group_id", None):
            instance.l3_assignment_group = session.query(AssignmentGroup).filter_by(id=instance.l3_assignment_group_id).first()
        if getattr(instance, "default_sla_policy_id", None):
            instance.default_sla_policy = session.query(SLAPolicy).filter_by(id=instance.default_sla_policy_id).first()
        if getattr(instance, "application_id", None):
            instance.application = session.query(Application).filter_by(id=instance.application_id).first()

    elif cls_name in ("RoutingRule", "ProjectAssignmentMapping"):
        from backend.models import AssignmentGroup
        if getattr(instance, "assignment_group_id", None):
            instance.assignment_group = session.query(AssignmentGroup).filter_by(id=instance.assignment_group_id).first()

    elif cls_name == "GroupMember":
        from backend.models import User, AssignmentGroup
        if getattr(instance, "user_id", None):
            instance.user = session.query(User).filter_by(id=instance.user_id).first()
        if getattr(instance, "group_id", None):
            instance.group = session.query(AssignmentGroup).filter_by(id=instance.group_id).first()


# ── MongoQuery Object ──

class MongoQuery:
    def __init__(self, session: 'MongoSession', model_cls: Type[Any]):
        self.session = session
        self.model_cls = model_cls
        self.collection_name = getattr(model_cls, "__tablename__", model_cls.__name__.lower())
        self.filter_dict: Dict[str, Any] = {}
        self.sort_criteria: List[Tuple[str, int]] = []
        self._limit_val: Optional[int] = None
        self._offset_val: int = 0

    def _clone(self) -> 'MongoQuery':
        q = MongoQuery(self.session, self.model_cls)
        q.filter_dict = copy.deepcopy(self.filter_dict)
        q.sort_criteria = list(self.sort_criteria)
        q._limit_val = self._limit_val
        q._offset_val = self._offset_val
        return q

    @property
    def collection(self):
        return self.session.db[self.collection_name]

    def filter(self, *criteria) -> 'MongoQuery':
        q = self._clone()
        for c in criteria:
            sub = expr_to_mongo(c)
            q.filter_dict = merge_filters(q.filter_dict, sub)
        return q

    def filter_by(self, **kwargs) -> 'MongoQuery':
        q = self._clone()
        q.filter_dict = merge_filters(q.filter_dict, kwargs)
        return q

    def order_by(self, *sort_args) -> 'MongoQuery':
        q = self._clone()
        for arg in sort_args:
            if hasattr(arg, "element") and hasattr(arg, "modifier"):
                field = getattr(arg.element, "key", getattr(arg.element, "name", str(arg.element)))
                direction = DESCENDING if arg.modifier.__name__ == "desc_op" else ASCENDING
                q.sort_criteria.append((field, direction))
            elif hasattr(arg, "key") or hasattr(arg, "name"):
                field = getattr(arg, "key", getattr(arg, "name", str(arg)))
                q.sort_criteria.append((field, ASCENDING))
            elif isinstance(arg, str):
                q.sort_criteria.append((arg, ASCENDING))
        return q

    def limit(self, n: int) -> 'MongoQuery':
        q = self._clone()
        q._limit_val = n
        return q

    def offset(self, n: int) -> 'MongoQuery':
        q = self._clone()
        q._offset_val = n
        return q

    def first(self) -> Optional[Any]:
        cursor = self.collection.find(self.filter_dict)
        if self.sort_criteria:
            cursor = cursor.sort(self.sort_criteria)
        if self._offset_val:
            cursor = cursor.skip(self._offset_val)
        cursor = cursor.limit(1)
        docs = list(cursor)
        if not docs:
            return None
        return doc_to_model(self.model_cls, docs[0], session=self.session)

    def all(self) -> List[Any]:
        cursor = self.collection.find(self.filter_dict)
        if self.sort_criteria:
            cursor = cursor.sort(self.sort_criteria)
        if self._offset_val:
            cursor = cursor.skip(self._offset_val)
        if self._limit_val is not None:
            cursor = cursor.limit(self._limit_val)
        return [doc_to_model(self.model_cls, d, session=self.session) for d in cursor]

    def count(self) -> int:
        return self.collection.count_documents(self.filter_dict)

    def __iter__(self):
        return iter(self.all())


# ── MongoSession Object ──

class MongoSession:
    def __init__(self, db: Optional[Any] = None):
        self.db = db if db is not None else get_mongo_db()
        self._staged_new: List[Any] = []
        self._staged_dirty: List[Any] = []
        self._staged_deleted: List[Any] = []
        self._queried: List[Any] = []
        self._identity_map: Dict[Tuple[str, Any], Any] = {}

    def query(self, model_cls: Type[Any]) -> MongoQuery:
        return MongoQuery(self, model_cls)

    def get(self, model_cls: Type[Any], ident: Any) -> Optional[Any]:
        if ident is None:
            return None
        collection_name = getattr(model_cls, "__tablename__", model_cls.__name__.lower())
        doc = self.db[collection_name].find_one({"$or": [{"_id": ident}, {"id": ident}]})
        return doc_to_model(model_cls, doc, session=self)

    def add(self, instance: Any):
        if instance not in self._staged_new and instance not in self._staged_dirty:
            collection_name = getattr(instance, "__tablename__", instance.__class__.__name__.lower())
            if getattr(instance, "id", None) is None:
                instance.id = get_next_id(collection_name)
            self._staged_new.append(instance)
            if getattr(instance, "id", None) is not None:
                self._identity_map[(instance.__class__.__name__, instance.id)] = instance
            hydrate_relationships(instance, self)

    def add_all(self, instances: List[Any]):
        for inst in instances:
            self.add(inst)

    def delete(self, instance: Any):
        if instance not in self._staged_deleted:
            self._staged_deleted.append(instance)
        while instance in self._queried:
            self._queried.remove(instance)
        while instance in self._staged_new:
            self._staged_new.remove(instance)
        while instance in self._staged_dirty:
            self._staged_dirty.remove(instance)
        collection_name = getattr(instance, "__tablename__", instance.__class__.__name__.lower())
        doc_id = getattr(instance, "id", None)
        if doc_id is not None:
            self.db[collection_name].delete_one({"$or": [{"_id": doc_id}, {"id": doc_id}]})
            self._identity_map.pop((instance.__class__.__name__, doc_id), None)

    def commit(self):
        # Save all new, dirty, and modified queried instances to Mongo collections
        deleted_set = set(self._staged_deleted)
        to_save = {}
        for inst in self._staged_new + self._staged_dirty + self._queried:
            if inst in deleted_set:
                continue
            inst_id = getattr(inst, "id", None)
            if inst_id is not None:
                to_save[(inst.__class__.__name__, inst_id)] = inst
            else:
                to_save[(inst.__class__.__name__, id(inst))] = inst

        for inst in to_save.values():
            collection_name = getattr(inst, "__tablename__", inst.__class__.__name__.lower())
            if getattr(inst, "id", None) is None:
                inst.id = get_next_id(collection_name)
            if getattr(inst, "id", None) is not None:
                self._identity_map[(inst.__class__.__name__, inst.id)] = inst
            hydrate_relationships(inst, self)
            doc = model_to_doc(inst)
            self.db[collection_name].replace_one(
                {"$or": [{"_id": inst.id}, {"id": inst.id}]},
                doc,
                upsert=True
            )
        self._staged_new.clear()
        self._staged_dirty.clear()
        self._staged_deleted.clear()
        self._queried.clear()

    def flush(self):
        for inst in list(self._staged_new):
            collection_name = getattr(inst, "__tablename__", inst.__class__.__name__.lower())
            if getattr(inst, "id", None) is None:
                inst.id = get_next_id(collection_name)
            if getattr(inst, "id", None) is not None:
                self._identity_map[(inst.__class__.__name__, inst.id)] = inst
            hydrate_relationships(inst, self)
            doc = model_to_doc(inst)
            self.db[collection_name].replace_one(
                {"$or": [{"_id": inst.id}, {"id": inst.id}]},
                doc,
                upsert=True
            )

    def refresh(self, instance: Any):
        collection_name = getattr(instance, "__tablename__", instance.__class__.__name__.lower())
        doc_id = getattr(instance, "id", None)
        if doc_id is not None:
            latest_doc = self.db[collection_name].find_one({"$or": [{"_id": doc_id}, {"id": doc_id}]})
            if latest_doc:
                for k, v in latest_doc.items():
                    if k != "_id" and hasattr(instance, k):
                        try:
                            setattr(instance, k, v)
                        except Exception:
                            pass
            hydrate_relationships(instance, self)

    def rollback(self):
        self._staged_new.clear()
        self._staged_dirty.clear()
        self._staged_deleted.clear()
        self._queried.clear()
        self._identity_map.clear()

    def close(self):
        self.rollback()


# ── Dependency Injector & Session Factory ──

_seeded = False
def ensure_seeded():
    global _seeded
    if not _seeded:
        db = get_mongo_db()
        if db["users"].count_documents({}) == 0:
            _seeded = True
            try:
                from backend.seed_data import init_db_and_seed
                init_db_and_seed()
            except Exception as e:
                logger.warning("Auto-seed error: %s", e)

def SessionLocal() -> MongoSession:
    ensure_seeded()
    return MongoSession()

def get_db():
    ensure_seeded()
    session = MongoSession()
    try:
        yield session
    finally:
        session.close()
