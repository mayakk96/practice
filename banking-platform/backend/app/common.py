from contextvars import ContextVar
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import inspect

from .errors import DomainError

request_context = ContextVar("request_id", default="system")
actor_context = ContextVar("actor", default="system")


def now():
    return datetime.now(UTC)


def actor():
    return actor_context.get()


def correlation_id():
    return request_context.get()


def camel(value):
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


def json_value(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def as_dict(entity):
    return {
        camel(column.key): json_value(getattr(entity, column.key))
        for column in inspect(entity).mapper.column_attrs
    }


def validate_page(page, size):
    if page < 0 or page > 100000 or size < 1 or size > 100:
        raise DomainError(400, "page must be 0..100000 and size must be 1..100.")
    return page, size


def page_result(items, page, size, total):
    return {"items": items, "page": page, "size": size, "total": total}
