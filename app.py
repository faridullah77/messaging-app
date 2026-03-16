import eventlet
eventlet.monkey_patch()

import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, FriendRequest, Message
from datetime import datetime

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
    # Mark all messages from friend as read
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
    if not content or not receiver_id:
        return
    receiver = User.query.get(receiver_id)
    if not receiver or not current_user.is_friend_with(receiver):
        return
    msg = Message(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        content=content
    )
    db.session.add(msg)
    db.session.commit()
    payload = {
        'message': content,
        'sender': current_user.username,
        'sender_id': current_user.id,
        'timestamp': msg.timestamp.strftime('%H:%M')
    }
    emit('receive_message', payload, room=f'user_{receiver_id}')
    emit('receive_message', payload, room=f'user_{current_user.id}')

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    socketio.run(app, debug=True)