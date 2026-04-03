from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from flask import flash, redirect, session, url_for

from db_utils import fetch_one


def go(endpoint: str) -> Any:
    if "#" in endpoint:
        name, anchor = endpoint.split("#", 1)
        return redirect(f"{url_for(name)}#{anchor}")
    return redirect(url_for(endpoint))


def get_current_user() -> dict[str, Any] | None:
    user_id = session.get("user_id")
    return fetch_one("SELECT * FROM users WHERE user_id = %s", (user_id,)) if user_id else None


def inject_session_user() -> dict[str, Any]:
    return {"current_user": get_current_user()}


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped_view(*args: Any, **kwargs: Any) -> Any:
        if get_current_user() is None:
            flash("Please log in first.")
            return go("login")
        return view(*args, **kwargs)

    return wrapped_view


def role_required(role: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped_view(*args: Any, **kwargs: Any) -> Any:
            user = get_current_user()
            if user is None:
                flash("Please log in first.")
                return go("login")
            if user["role"] != role:
                flash("You do not have permission to open that page.")
                return go("dashboard")
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def dashboard_redirect() -> Any:
    user = get_current_user()
    if user is None:
        return go("login")
    return go("owner_dashboard" if user["role"] == "Owner" else "customer_dashboard")
