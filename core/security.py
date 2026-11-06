import functools
from flask import session, redirect, url_for, request, jsonify, abort
from typing import Optional, Dict, Any
from db.repositories import UserRepository

def get_current_user() -> Optional[Dict[str, Any]]:
    """Retrieves the authenticated user dict from session, or None."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return UserRepository.get_by_id(user_id)

def login_required(f):
    """Decorator requiring a valid active session. Redirects to /login or returns 401."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            if request.path.startswith('/api/') or request.is_json:
                return jsonify({
                    "success": False,
                    "message": "Authentication required. Please sign in.",
                    "redirect": "/login"
                }), 401
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator requiring Administrator privileges. Rejects analyst role with 403."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            if request.path.startswith('/api/') or request.is_json:
                return jsonify({
                    "success": False,
                    "message": "Authentication required. Please sign in.",
                    "redirect": "/login"
                }), 401
            return redirect(url_for('auth.login', next=request.url))
        
        user_role = session.get('user_role')
        if user_role != 'admin':
            if request.path.startswith('/api/') or request.is_json:
                return jsonify({
                    "success": False,
                    "message": "Administrator privileges required for this action."
                }), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

