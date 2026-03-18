import eventlet
eventlet.monkey_patch()

import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, FriendRequest, Message, Reaction
from datetime import datetime
from flask_mail import Mail, Message as MailMessage
from itsdangerous import URLSafeTimedSerializer

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey123')

database_url = os.environ.get('DATABASE_URL', '')
print(f"DATABASE_URL found: {bool(database_url)}")
if not database_url:
    database_url = 'postgresql://localhost/messaging_app'
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# ── Mail Config ──
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_EMAIL')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_EMAIL')

mail = Mail(app)
serializer = URLSafeTimedSerializer(app.secret_key)

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ── Auth Routes ──
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('friends'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('friends'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            user.is_online = True
            db.session.commit()
            return redirect(url_for('friends'))
        flash('Invalid email or password')
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('friends'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        if User.query.filter_by(username=username).first():
            flash('Username already taken')
        elif User.query.filter_by(email=email).first():
            flash('Email already registered')
        else:
            user = User(
                username=username,
                email=email,
                password=generate_password_hash(password)
            )
            db.session.add(user)
            db.session.commit()
            login_user(user)
            user.is_online = True
            db.session.commit()
            return redirect(url_for('friends'))
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    current_user.is_online = False
    db.session.commit()
    logout_user()
    return redirect(url_for('login'))

# ── Friends Routes ──
@app.route('/friends')
@login_required
def friends():
    friends_list = current_user.get_friends()
    pending_requests = FriendRequest.query.filter_by(
        receiver_id=current_user.id, status='pending'
    ).all()
    unread_counts = {}
    for friend in friends_list:
        count = Message.query.filter_by(
            sender_id=friend.id,
            receiver_id=current_user.id,
            is_read=False
        ).count()
        unread_counts[friend.id] = count
    return render_template('friends.html',
                           friends=friends_list,
                           pending_requests=pending_requests,
                           unread_counts=unread_counts)

@app.route('/search_users')
@login_required
def search_users():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    users = User.query.filter(
        User.username.ilike(f'%{query}%'),
        User.id != current_user.id
    ).limit(10).all()
    results = []
    for user in users:
        results.append({
            'id': user.id,
            'username': user.username,
            'is_online': user.is_online,
            'is_friend': current_user.is_friend_with(user),
            'has_pending': current_user.has_pending_request(user)
        })
    return jsonify(results)

@app.route('/send_request/<int:user_id>', methods=['POST'])
@login_required
def send_request(user_id):
    user = User.query.get_or_404(user_id)
    if not current_user.is_friend_with(user) and not current_user.has_pending_request(user):
        req = FriendRequest(sender_id=current_user.id, receiver_id=user_id)
        db.session.add(req)
        db.session.commit()
    return jsonify({'success': True})

@app.route('/accept_request/<int:request_id>', methods=['POST'])
@login_required
def accept_request(request_id):
    req = FriendRequest.query.get_or_404(request_id)
    if req.receiver_id == current_user.id:
        req.status = 'accepted'
        db.session.commit()
    return redirect(url_for('friends'))

@app.route('/reject_request/<int:request_id>', methods=['POST'])
@login_required
def reject_request(request_id):
    req = FriendRequest.query.get_or_404(request_id)
    if req.receiver_id == current_user.id:
        req.status = 'rejected'
        db.session.commit()
    return redirect(url_for('friends'))

# ── Chat Route ──
@app.route('/chat/<int:friend_id>')
@login_required
def chat(friend_id):
    friend = User.query.get_or_404(friend_id)
    if not current_user.is_friend_with(friend):
        return redirect(url_for('friends'))
    Message.query.filter_by(
        sender_id=friend_id,
        receiver_id=current_user.id,
        is_read=False
    ).update({'is_read': True})
    db.session.commit()
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == friend_id)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()
    return render_template('chat.html',
                           friend=friend,
                           messages=messages,
                           current_user=current_user)

# ── Search Messages ──
@app.route('/search_messages/<int:friend_id>')
@login_required
def search_messages(friend_id):
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == friend_id)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == current_user.id)),
        Message.content.ilike(f'%{query}%'),
        Message.is_deleted == False
    ).order_by(Message.timestamp.asc()).all()
    results = []
    for msg in messages:
        results.append({
            'id': msg.id,
            'content': msg.content,
            'sender_id': msg.sender_id,
            'timestamp': msg.timestamp.strftime('%H:%M')
        })
    return jsonify(results)

# ── Delete Message ──
@app.route('/delete_message/<int:msg_id>', methods=['POST'])
@login_required
def delete_message(msg_id):
    msg = Message.query.get_or_404(msg_id)
    if msg.sender_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    delete_for = request.json.get('delete_for', 'me') if request.json else 'me'
    if delete_for == 'everyone':
        msg.content = 'This message was deleted'
        msg.is_deleted = True
        db.session.commit()
        other_id = msg.receiver_id if msg.sender_id == current_user.id else msg.sender_id
        socketio.emit('message_deleted', {'msg_id': msg_id}, room=f'user_{other_id}')
        socketio.emit('message_deleted', {'msg_id': msg_id}, room=f'user_{current_user.id}')
    else:
        msg.is_deleted = True
        db.session.commit()
    return jsonify({'success': True})

# ── Reactions ──
@app.route('/react/<int:msg_id>', methods=['POST'])
@login_required
def react_message(msg_id):
    emoji = request.json.get('emoji')
    if not emoji:
        return jsonify({'success': False})
    existing = Reaction.query.filter_by(
        message_id=msg_id,
        user_id=current_user.id,
        emoji=emoji
    ).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'success': True, 'action': 'removed'})
    Reaction.query.filter_by(message_id=msg_id, user_id=current_user.id).delete()
    reaction = Reaction(message_id=msg_id, user_id=current_user.id, emoji=emoji)
    db.session.add(reaction)
    db.session.commit()
    return jsonify({'success': True, 'action': 'added'})
# ── Forgot Password ──
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()
        if user:
            token = serializer.dumps(email, salt='password-reset')
            reset_url = url_for('reset_password', token=token, _external=True)
            msg = MailMessage(
                subject='Password Reset - Messenger App',
                recipients=[email],
                body=f'''Hi {user.username}!

Click the link below to reset your password:
{reset_url}

This link will expire in 1 hour.

If you did not request a password reset, ignore this email.
'''
            )
            mail.send(msg)
        flash('Agar email registered hai toh reset link bhej diya gaya hai!')
        return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = serializer.loads(token, salt='password-reset', max_age=3600)
    except:
        flash('Reset link expired ya invalid hai!')
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if password != confirm:
            flash('Passwords match nahi kar rahe!')
            return render_template('reset_password.html', token=token)
        if len(password) < 6:
            flash('Password kam az kam 6 characters ka hona chahiye!')
            return render_template('reset_password.html', token=token)
        user = User.query.filter_by(email=email).first()
        if user:
            user.password = generate_password_hash(password)
            db.session.commit()
            flash('Password reset ho gaya! Ab login karo.')
            return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)

# ── Socket Events ──
@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        current_user.is_online = True
        db.session.commit()
        join_room(f'user_{current_user.id}')

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        current_user.is_online = False
        db.session.commit()

@socketio.on('send_message')
def handle_message(data):
    if not current_user.is_authenticated:
        return
    receiver_id = data.get('receiver_id')
    content = data.get('message', '').strip()
    reply_to_id = data.get('reply_to_id')
    if not content or not receiver_id:
        return
    receiver = User.query.get(receiver_id)
    if not receiver or not current_user.is_friend_with(receiver):
        return
    msg = Message(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        content=content,
        is_read=False,
        reply_to_id=reply_to_id
    )
    db.session.add(msg)
    db.session.commit()
    reply_preview = None
    if reply_to_id:
        reply_msg = Message.query.get(reply_to_id)
        if reply_msg:
            reply_preview = {
                'content': reply_msg.content[:50],
                'sender_id': reply_msg.sender_id
            }
    payload = {
        'message': content,
        'sender': current_user.username,
        'sender_id': current_user.id,
        'timestamp': msg.timestamp.strftime('%H:%M'),
        'msg_id': msg.id,
        'is_read': False,
        'reply_preview': reply_preview
    }
    emit('receive_message', payload, room=f'user_{receiver_id}')
    emit('receive_message', payload, room=f'user_{current_user.id}')

@socketio.on('message_seen')
def handle_message_seen(data):
    if not current_user.is_authenticated:
        return
    msg_id = data.get('msg_id')
    msg = Message.query.get(msg_id)
    if msg and msg.receiver_id == current_user.id:
        msg.is_read = True
        db.session.commit()
        emit('message_read', {'msg_id': msg_id}, room=f'user_{msg.sender_id}')

@socketio.on('send_reaction')
def handle_reaction(data):
    if not current_user.is_authenticated:
        return
    msg_id = data.get('msg_id')
    emoji = data.get('emoji')
    msg = Message.query.get(msg_id)
    if not msg:
        return
    existing = Reaction.query.filter_by(
        message_id=msg_id,
        user_id=current_user.id
    ).first()
    if existing:
        if existing.emoji == emoji:
            db.session.delete(existing)
            db.session.commit()
        else:
            existing.emoji = emoji
            db.session.commit()
    else:
        reaction = Reaction(message_id=msg_id, user_id=current_user.id, emoji=emoji)
        db.session.add(reaction)
        db.session.commit()
    reactions = Reaction.query.filter_by(message_id=msg_id).all()
    result = {}
    for r in reactions:
        result[r.emoji] = result.get(r.emoji, 0) + 1
    other_user_id = msg.receiver_id if msg.sender_id == current_user.id else msg.sender_id
    payload = {'msg_id': msg_id, 'reactions': result}
    emit('reaction_updated', payload, room=f'user_{current_user.id}')
    emit('reaction_updated', payload, room=f'user_{other_user_id}')

@socketio.on('typing')
def handle_typing(data):
    if not current_user.is_authenticated:
        return
    receiver_id = data.get('receiver_id')
    emit('user_typing', {
        'sender': current_user.username,
        'sender_id': current_user.id
    }, room=f'user_{receiver_id}')

@socketio.on('stop_typing')
def handle_stop_typing(data):
    if not current_user.is_authenticated:
        return
    receiver_id = data.get('receiver_id')
    emit('user_stop_typing', {
        'sender_id': current_user.id
    }, room=f'user_{receiver_id}')

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    socketio.run(app, debug=True)