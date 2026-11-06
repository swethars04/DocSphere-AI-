import logging
import random
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from config import Config
from db.repositories import UserRepository
from core.security import login_required, admin_required

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__)

AVATAR_PALETTE = ['#10b981', '#06b6d4', '#6366f1', '#8b5cf6', '#ec4899', '#f59e0b', '#3b82f6']

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Renders login interface or processes user credentials."""
    # If already logged in, redirect to workspace
    if session.get('user_id'):
        return redirect(url_for('frontend.index'))

    next_url = request.args.get('next') or request.form.get('next') or url_for('frontend.index')
    # Prevent open redirect vulnerabilities
    if not next_url.startswith('/'):
        next_url = url_for('frontend.index')

    if request.method == 'POST':
        is_json = request.is_json
        data = request.get_json() if is_json else request.form

        email = (data.get('email') or '').strip().lower()
        password = data.get('password') or ''

        if not email or not password:
            msg = "Email and password are required."
            if is_json:
                return jsonify({"success": False, "message": msg}), 400
            return render_template('login.html', error_msg=msg, next_url=next_url)

        user = UserRepository.get_by_email(email)
        if not user or not UserRepository.verify_password(user['password_hash'], password):
            msg = "Invalid email or password. Please try again."
            if is_json:
                return jsonify({"success": False, "message": msg}), 401
            return render_template('login.html', error_msg=msg, next_url=next_url)

        # Set authenticated session
        session.clear()
        session['user_id'] = user['id']
        session['user_email'] = user['email']
        session['user_name'] = user['full_name']
        session['user_role'] = user['role']
        session['avatar_color'] = user.get('avatar_color', '#10b981')
        session.permanent = True

        UserRepository.update_last_login(user['id'])
        logger.info(f"User logged in successfully: {user['email']} (role: {user['role']})")

        if is_json:
            return jsonify({"success": True, "redirect": next_url, "user": {
                "id": user['id'],
                "email": user['email'],
                "name": user['full_name'],
                "role": user['role']
            }})
        return redirect(next_url)

    return render_template('login.html', next_url=next_url)


@auth_bp.route('/register', methods=['POST'])
def register():
    """Registers a new organization member with role assignment."""
    is_json = request.is_json
    data = request.get_json() if is_json else request.form

    full_name = (data.get('full_name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    admin_code = (data.get('admin_code') or '').strip()
    next_url = data.get('next') or url_for('frontend.index')

    if not full_name or not email or not password:
        msg = "All fields (Name, Email, Password) are required."
        if is_json:
            return jsonify({"success": False, "message": msg}), 400
        return render_template('login.html', error_msg=msg, active_tab='register', next_url=next_url)

    if len(password) < 6:
        msg = "Password must be at least 6 characters long."
        if is_json:
            return jsonify({"success": False, "message": msg}), 400
        return render_template('login.html', error_msg=msg, active_tab='register', next_url=next_url)

    # Principle of Least Privilege:
    # If admin passcode is entered, verify against Config.ADMIN_INVITE_CODE.
    # If correct -> assign 'admin'. If wrong -> return error.
    # If blank -> automatically grant safe 'analyst' role.
    if admin_code:
        if admin_code == Config.ADMIN_INVITE_CODE:
            role = 'admin'
        else:
            msg = "Invalid Admin Security Passcode. Leave blank to register as an Analyst, or enter the correct key."
            if is_json:
                return jsonify({"success": False, "message": msg}), 400
            return render_template('login.html', error_msg=msg, active_tab='register', next_url=next_url)
    else:
        role = 'analyst'

    existing = UserRepository.get_by_email(email)
    if existing:
        msg = "An account with this email address already exists."
        if is_json:
            return jsonify({"success": False, "message": msg}), 409
        return render_template('login.html', error_msg=msg, active_tab='register', next_url=next_url)

    # Pick an avatar color
    avatar_color = random.choice(AVATAR_PALETTE)
    try:
        user = UserRepository.create_user(
            email=email,
            password=password,
            full_name=full_name,
            role=role if role in ('admin', 'analyst') else 'analyst',
            avatar_color=avatar_color
        )
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        msg = "Could not register user. Please try again."
        if is_json:
            return jsonify({"success": False, "message": msg}), 500
        return render_template('login.html', error_msg=msg, active_tab='register', next_url=next_url)

    # Establish session
    session.clear()
    session['user_id'] = user['id']
    session['user_email'] = user['email']
    session['user_name'] = user['full_name']
    session['user_role'] = user['role']
    session['avatar_color'] = user.get('avatar_color', avatar_color)
    session.permanent = True

    logger.info(f"New user registered: {user['email']} (role: {user['role']})")

    if is_json:
        return jsonify({"success": True, "redirect": next_url, "user": user})
    return redirect(next_url)


@auth_bp.route('/demo-login/<persona>', methods=['GET', 'POST'])
def demo_login(persona: str):
    """One-click instant login for live interview demonstrations."""
    persona_map = {
        'admin': 'admin@docusphere.ai',
        'analyst': 'analyst@docusphere.ai'
    }
    email = persona_map.get(persona.lower())
    if not email:
        return redirect(url_for('auth.login'))

    user = UserRepository.get_by_email(email)
    if not user:
        return redirect(url_for('auth.login'))

    session.clear()
    session['user_id'] = user['id']
    session['user_email'] = user['email']
    session['user_name'] = user['full_name']
    session['user_role'] = user['role']
    session['avatar_color'] = user.get('avatar_color', '#10b981')
    session.permanent = True

    UserRepository.update_last_login(user['id'])
    logger.info(f"Demo login activated for persona: {persona} ({email})")

    if request.is_json:
        return jsonify({"success": True, "redirect": url_for('frontend.index')})
    return redirect(url_for('frontend.index'))


@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    """Terminates session and returns to login screen."""
    email = session.get('user_email')
    session.clear()
    logger.info(f"User logged out: {email}")
    return redirect(url_for('auth.login'))


@auth_bp.route('/api/auth/me', methods=['GET'])
def get_me():
    """Returns profile for currently authenticated user."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"success": False, "authenticated": False}), 401
    user = UserRepository.get_by_id(user_id)
    return jsonify({"success": True, "authenticated": True, "user": user})


@auth_bp.route('/profile')
@login_required
def profile():
    """Renders the comprehensive User Profile, Security & Account Settings workspace."""
    user_id = session.get('user_id')
    user = UserRepository.get_by_id(user_id)
    stats = UserRepository.get_user_stats(user_id)
    return render_template('profile.html', profile_user=user, stats=stats)


@auth_bp.route('/api/user/profile', methods=['POST'])
@login_required
def update_profile():
    """Updates user display name and avatar color."""
    user_id = session.get('user_id')
    data = request.get_json() or {}
    full_name = (data.get('full_name') or '').strip()
    avatar_color = (data.get('avatar_color') or '').strip()

    if not full_name:
        return jsonify({"success": False, "message": "Full name cannot be empty."}), 400

    success = UserRepository.update_profile(user_id, full_name, avatar_color)
    if success:
        session['user_name'] = full_name
        if avatar_color:
            session['avatar_color'] = avatar_color
        return jsonify({"success": True, "message": "Profile updated successfully.", "full_name": full_name, "avatar_color": avatar_color})
    return jsonify({"success": False, "message": "Failed to update profile."}), 500


@auth_bp.route('/api/user/password', methods=['POST'])
@login_required
def update_password():
    """Verifies existing password and updates to new password."""
    user_id = session.get('user_id')
    data = request.get_json() or {}
    current_password = data.get('current_password') or ''
    new_password = data.get('new_password') or ''

    if not current_password or not new_password:
        return jsonify({"success": False, "message": "Current and new password are required."}), 400

    if len(new_password) < 6:
        return jsonify({"success": False, "message": "New password must be at least 6 characters long."}), 400

    user = UserRepository.get_by_email(session.get('user_email', ''))
    if not user or not UserRepository.verify_password(user['password_hash'], current_password):
        return jsonify({"success": False, "message": "Current password is incorrect."}), 400

    success = UserRepository.update_password(user_id, new_password)
    if success:
        return jsonify({"success": True, "message": "Password updated successfully."})
    return jsonify({"success": False, "message": "Failed to update password."}), 500


@auth_bp.route('/api/user/delete', methods=['POST'])
@login_required
def delete_own_account():
    """Allows user to self-delete their account with password confirmation."""
    user_id = session.get('user_id')
    if user_id == 1:
        return jsonify({"success": False, "message": "The primary Compliance Admin account is protected and cannot be deleted."}), 403

    data = request.get_json() or {}
    password = data.get('password') or ''
    if not password:
        return jsonify({"success": False, "message": "Please enter your password to confirm account deletion."}), 400

    user = UserRepository.get_by_email(session.get('user_email', ''))
    if not user or not UserRepository.verify_password(user['password_hash'], password):
        return jsonify({"success": False, "message": "Password verification failed. Incorrect password."}), 400

    success = UserRepository.delete_user(user_id)
    if success:
        email = session.get('user_email')
        session.clear()
        logger.info(f"User account self-deleted: {email} (ID: {user_id})")
        return jsonify({"success": True, "redirect": url_for('auth.login'), "message": "Account deleted successfully."})
    return jsonify({"success": False, "message": "Failed to delete account."}), 500


@auth_bp.route('/api/users/<int:target_user_id>', methods=['DELETE', 'POST'])
@admin_required
def admin_delete_user(target_user_id: int):
    """Compliance Admin can delete other user accounts from the database inspector."""
    if target_user_id == 1:
        return jsonify({"success": False, "message": "The primary Compliance Admin account is protected and cannot be deleted."}), 403

    current_uid = session.get('user_id')
    if target_user_id == current_uid:
        return jsonify({"success": False, "message": "To delete your own account, please use the Delete Account option in Profile Settings."}), 400

    success = UserRepository.delete_user(target_user_id)
    if success:
        logger.info(f"Admin (ID: {current_uid}) deleted user ID: {target_user_id}")
        return jsonify({"success": True, "message": f"User #{target_user_id} deleted successfully."})
    return jsonify({"success": False, "message": "Failed to delete user."}), 500

