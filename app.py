import eventlet
eventlet.monkey_patch()

import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, FriendRequest, Message, Reaction, PushSubscription
from datetime import datetime
from flask_mail import Mail, Message as MailMessage
from itsdangerous import URLSafeTimedSerializer
import cloudinary
import cloudinary.uploader
from pywebpush import webpush, WebPushException
import json
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
# ── Cloudinary Config ──
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)
# ── VAPID Config ──
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', '')
VAPID_EMAIL = os.environ.get('VAPID_EMAIL', 'mailto:test@test.com')

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
    current_user.last_seen = datetime.utcnow()
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

    # Mark all messages from this friend as READ when I open the chat
    unread_messages = Message.query.filter_by(
        sender_id=friend_id,
        receiver_id=current_user.id,
        is_read=False
    ).all()

    if unread_messages:
        for msg in unread_messages:
            msg.is_read = True
            msg.read_at = datetime.utcnow()
            # Notify the sender that I've read their messages
            socketio.emit('message_read', {
                'msg_id': msg.id,
                'read_at': msg.read_at.isoformat()
            }, room=f'user_{friend_id}')
        db.session.commit()

    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == friend_id)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()

    return render_template('chat.html', friend=friend, messages=messages)
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
# ── Image Upload ──
@app.route('/upload_image', methods=['POST'])
@login_required
def upload_image():
    if 'image' not in request.files:
        return jsonify({'success': False, 'error': 'No image'})
    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'})
    try:
        result = cloudinary.uploader.upload(
            file,
            folder='messaging_app',
            allowed_formats=['jpg', 'jpeg', 'png', 'gif', 'webp'],
            max_bytes=5000000
        )
        image_url = result['secure_url']
        receiver_id = request.form.get('receiver_id', type=int)
        receiver = User.query.get(receiver_id)
        if not receiver or not current_user.is_friend_with(receiver):
            return jsonify({'success': False, 'error': 'Unauthorized'})
        view_once = request.form.get('view_once') == 'true'
        msg = Message(
            sender_id=current_user.id,
            receiver_id=receiver_id,
            content=f'[IMAGE]{image_url}[/IMAGE]',
            is_read=False,
            view_once=view_once
        )
        db.session.add(msg)
        db.session.commit()
        payload = {
            'message': f'[IMAGE]{image_url}[/IMAGE]',
            'sender': current_user.username,
            'sender_id': current_user.id,
            'timestamp': msg.timestamp.strftime('%H:%M'),
            'msg_id': msg.id,
            'is_read': False,
            'reply_preview': None,
            'view_once': view_once
        }
        socketio.emit('receive_message', payload, room=f'user_{receiver_id}')
        socketio.emit('receive_message', payload, room=f'user_{current_user.id}')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ── Edit Message ──
@app.route('/edit_message/<int:msg_id>', methods=['POST'])
@login_required
def edit_message(msg_id):
    msg = Message.query.get_or_404(msg_id)
    if msg.sender_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    if msg.is_deleted:
        return jsonify({'success': False, 'error': 'Deleted message edit nahi ho sakta'})
    new_content = request.json.get('content', '').strip()
    if not new_content:
        return jsonify({'success': False, 'error': 'Empty message'})
    msg.content = new_content
    msg.is_edited = True
    db.session.commit()
    other_id = msg.receiver_id if msg.sender_id == current_user.id else msg.sender_id
    socketio.emit('message_edited', {
        'msg_id': msg_id,
        'new_content': new_content
    }, room=f'user_{other_id}')
    socketio.emit('message_edited', {
        'msg_id': msg_id,
        'new_content': new_content
    }, room=f'user_{current_user.id}')
    return jsonify({'success': True})
# ── Push Notifications ──
@app.route('/get_vapid_public_key')
def get_vapid_public_key():
    return jsonify({'public_key': VAPID_PUBLIC_KEY})

@app.route('/save_subscription', methods=['POST'])
@login_required
def save_subscription():
    subscription = request.json
    if not subscription:
        return jsonify({'success': False})
    # Delete old subscriptions for this user
    PushSubscription.query.filter_by(user_id=current_user.id).delete()
    sub = PushSubscription(
        user_id=current_user.id,
        subscription_json=json.dumps(subscription)
    )
    db.session.add(sub)
    db.session.commit()
    return jsonify({'success': True})

def send_push_notification(user_id, title, body):
    subscriptions = PushSubscription.query.filter_by(user_id=user_id).all()
    for sub in subscriptions:
        try:
            webpush(
                subscription_info=json.loads(sub.subscription_json),
                data=json.dumps({'title': title, 'body': body}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={'sub': VAPID_EMAIL}
            )
        except WebPushException as e:
            print(f"Push notification failed: {e}")
            if '410' in str(e):
                db.session.delete(sub)
                db.session.commit()
# ── Upload Avatar ──
@app.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': 'No image'})
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'})
    try:
        result = cloudinary.uploader.upload(
            file,
            folder='farasma_avatars',
            allowed_formats=['jpg', 'jpeg', 'png', 'webp'],
            max_bytes=2000000,
            transformation=[
                {'width': 200, 'height': 200, 'crop': 'fill', 'gravity': 'face'}
            ]
        )
        current_user.avatar_url = result['secure_url']
        db.session.commit()
        return jsonify({'success': True, 'avatar_url': current_user.avatar_url})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    # ── Update Bio ──
@app.route('/update_bio', methods=['POST'])
@login_required
def update_bio():
    bio = request.json.get('bio', '').strip()
    if len(bio) > 150:
        return jsonify({'success': False, 'error': 'Bio 150 characters se zyada nahi ho sakti'})
    current_user.bio = bio
    db.session.commit()
    return jsonify({'success': True})
# ── View Once ──
@app.route('/view_once/<int:msg_id>', methods=['POST'])
@login_required
def view_once_image(msg_id):
    msg = Message.query.get_or_404(msg_id)
    if msg.receiver_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'})
    if msg.view_once and not msg.viewed:
        msg.viewed = True
        msg.content = '[VIEW_ONCE_VIEWED]'
        db.session.commit()
        # Notify sender
        other_id = msg.sender_id
        socketio.emit('view_once_viewed', {'msg_id': msg_id}, room=f'user_{other_id}')
        socketio.emit('view_once_viewed', {'msg_id': msg_id}, room=f'user_{current_user.id}')
        return jsonify({'success': True})
    return jsonify({'success': False})
# ── Profile Page ──
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_profile':
            username = request.form.get('username', '').strip()
            bio = request.form.get('bio', '').strip()
            if username and username != current_user.username:
                if User.query.filter_by(username=username).first():
                    flash('Username already taken!')
                    return redirect(url_for('profile'))
            if username:
                current_user.username = username
            current_user.bio = bio
            db.session.commit()
            flash('Profile updated! ✅')

        elif action == 'update_email':
            email = request.form.get('email', '').strip()
            password = request.form.get('current_password_email', '')
            if not check_password_hash(current_user.password, password):
                flash('Wrong password!')
                return redirect(url_for('profile'))
            if email != current_user.email:
                if User.query.filter_by(email=email).first():
                    flash('Email already registered!')
                    return redirect(url_for('profile'))
            current_user.email = email
            db.session.commit()
            flash('Email updated! ✅')

        elif action == 'update_password':
            old_password = request.form.get('old_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')
            if not check_password_hash(current_user.password, old_password):
                flash('Current password galat hai!')
                return redirect(url_for('profile'))
            if new_password != confirm_password:
                flash('Naye passwords match nahi kar rahe!')
                return redirect(url_for('profile'))
            if len(new_password) < 6:
                flash('Password kam az kam 6 characters ka hona chahiye!')
                return redirect(url_for('profile'))
            current_user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Password updated! ✅')

        return redirect(url_for('profile'))
    return render_template('profile.html')
# ── Message Statistics ──
@app.route('/stats/<int:friend_id>')
@login_required
def message_stats(friend_id):
    friend = User.query.get_or_404(friend_id)
    
    sent = Message.query.filter_by(
        sender_id=current_user.id,
        receiver_id=friend_id
    ).count()

    received = Message.query.filter_by(
        sender_id=friend_id,
        receiver_id=current_user.id
    ).count()

    sent_images = Message.query.filter(
        Message.sender_id == current_user.id,
        Message.receiver_id == friend_id,
        Message.content.like('%[IMAGE]%')
    ).count()

    received_images = Message.query.filter(
        Message.sender_id == friend_id,
        Message.receiver_id == current_user.id,
        Message.content.like('%[IMAGE]%')
    ).count()

    first_msg = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == friend_id)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.asc()).first()

    days_chatting = 0
    if first_msg:
        days_chatting = (datetime.utcnow() - first_msg.timestamp).days + 1

    return jsonify({
        'sent': sent,
        'received': received,
        'total': sent + received,
        'sent_images': sent_images,
        'received_images': received_images,
        'days_chatting': days_chatting,
        'friend_username': friend.username
    })
    # First message date
    first_msg = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == friend_id)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.asc()).first()

    days_chatting = 0
    if first_msg:
        days_chatting = (datetime.utcnow() - first_msg.timestamp).days + 1

    return jsonify({
        'sent': sent,
        'received': received,
        'total': sent + received,
        'sent_images': sent_images,
        'received_images': received_images,
        'days_chatting': days_chatting,
        'friend_username': friend.username
    })
from datetime import datetime, timedelta

def get_last_seen_text(last_seen_time):
    if not last_seen_time:
        return "Offline"
    
    now = datetime.utcnow()
    diff = now - last_seen_time

    if diff < timedelta(minutes=1):
        return "Just now"
    if diff < timedelta(hours=1):
        return f"{int(diff.seconds / 60)}m ago"
    if diff < timedelta(days=1):
        return f"{int(diff.seconds / 3600)}h ago"
    if diff < timedelta(days=2):
        return "Yesterday"
    
    return last_seen_time.strftime('%b %d')

# Make this function available in your Jinja2 templates
@app.context_processor
def utility_processor():
    return dict(get_last_seen_text=get_last_seen_text)
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
        current_user.last_seen = datetime.utcnow()
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
    # Send push notification to receiver
    try:
        send_push_notification(
            receiver_id,
            f'New message from {current_user.username}',
            content[:100]
        )
    except Exception as e:
        print(f"Push notification error: {e}")

@socketio.on('message_seen')
def handle_message_seen(data):
    if not current_user.is_authenticated:
        return
    msg_id = data.get('msg_id')
    msg = Message.query.get(msg_id)
    if msg and msg.receiver_id == current_user.id:
        msg.is_read = True
        msg.read_at = datetime.utcnow()
        db.session.commit()
        read_at_str = msg.read_at.isoformat()
        emit('message_read', {
            'msg_id': msg_id,
            'read_at': read_at_str
        }, room=f'user_{msg.sender_id}')

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
    # Add to your app.py

# ── Group Chat Routes ──
@app.route('/create_group', methods=['POST'])
@login_required
def create_group():
    data = request.json
    group = Group(
        name=data['name'],
        description=data.get('description', ''),
        created_by=current_user.id
    )
    db.session.add(group)
    db.session.commit()
    
    # Add creator as admin
    member = GroupMember(group_id=group.id, user_id=current_user.id, role='admin')
    db.session.add(member)
    
    # Add other members
    for user_id in data.get('members', []):
        member = GroupMember(group_id=group.id, user_id=user_id, role='member')
        db.session.add(member)
    
    db.session.commit()
    return jsonify({'success': True, 'group_id': group.id})

@app.route('/group_chat/<int:group_id>')
@login_required
def group_chat(group_id):
    group = Group.query.get_or_404(group_id)
    member = GroupMember.query.filter_by(group_id=group_id, user_id=current_user.id).first()
    if not member:
        return redirect(url_for('friends'))
    
    messages = GroupMessage.query.filter_by(group_id=group_id).order_by(GroupMessage.timestamp.asc()).all()
    members = GroupMember.query.filter_by(group_id=group_id).all()
    
    return render_template('group_chat.html', group=group, messages=messages, members=members)

@socketio.on('send_group_message')
def handle_group_message(data):
    if not current_user.is_authenticated:
        return
    
    group_id = data.get('group_id')
    content = data.get('message', '').strip()
    
    group = Group.query.get(group_id)
    if not group:
        return
    
    member = GroupMember.query.filter_by(group_id=group_id, user_id=current_user.id).first()
    if not member:
        return
    
    msg = GroupMessage(
        group_id=group_id,
        sender_id=current_user.id,
        content=content
    )
    db.session.add(msg)
    db.session.commit()
    
    payload = {
        'message': content,
        'sender': current_user.username,
        'sender_id': current_user.id,
        'timestamp': msg.timestamp.strftime('%H:%M'),
        'msg_id': msg.id
    }
    
    # Send to all group members
    members = GroupMember.query.filter_by(group_id=group_id).all()
    for member in members:
        emit('receive_group_message', payload, room=f'user_{member.user_id}')

# ── Voice Message Upload ──
@app.route('/upload_voice', methods=['POST'])
@login_required
def upload_voice():
    if 'voice' not in request.files:
        return jsonify({'success': False, 'error': 'No voice file'})
    
    file = request.files['voice']
    duration = request.form.get('duration', type=int)
    receiver_id = request.form.get('receiver_id', type=int)
    
    try:
        result = cloudinary.uploader.upload(
            file,
            folder='messaging_app_voice',
            resource_type='auto'
        )
        
        msg = Message(
            sender_id=current_user.id,
            receiver_id=receiver_id,
            content='[VOICE]',
            is_read=False
        )
        db.session.add(msg)
        db.session.commit()
        
        voice_msg = VoiceMessage(
            message_id=msg.id,
            audio_url=result['secure_url'],
            duration=duration
        )
        db.session.add(voice_msg)
        db.session.commit()
        
        payload = {
            'message': '[VOICE]',
            'sender': current_user.username,
            'sender_id': current_user.id,
            'timestamp': msg.timestamp.strftime('%H:%M'),
            'msg_id': msg.id,
            'voice_url': result['secure_url'],
            'duration': duration
        }
        
        socketio.emit('receive_voice', payload, room=f'user_{receiver_id}')
        socketio.emit('receive_voice', payload, room=f'user_{current_user.id}')
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ── Stories ──
@app.route('/upload_story', methods=['POST'])
@login_required
def upload_story():
    if 'story' not in request.files:
        return jsonify({'success': False})
    
    file = request.files['story']
    caption = request.form.get('caption', '')
    
    try:
        result = cloudinary.uploader.upload(
            file,
            folder='messaging_app_stories',
            transformation=[
                {'width': 1080, 'height': 1920, 'crop': 'limit'}
            ]
        )
        
        story = Story(
            user_id=current_user.id,
            media_url=result['secure_url'],
            media_type='image',
            caption=caption
        )
        db.session.add(story)
        db.session.commit()
        
        return jsonify({'success': True, 'story_id': story.id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stories')
@login_required
def view_stories():
    # Get stories from friends
    friends = current_user.get_friends()
    stories_data = []
    
    for friend in friends:
        stories = Story.query.filter(
            Story.user_id == friend.id,
            Story.expires_at > datetime.utcnow()
        ).all()
        
        if stories:
            stories_data.append({
                'user': friend,
                'stories': stories
            })
    
    return render_template('stories.html', stories=stories_data)

# ── Block User ──
@app.route('/block_user/<int:user_id>', methods=['POST'])
@login_required
def block_user(user_id):
    user_to_block = User.query.get_or_404(user_id)
    
    # Check if already blocked
    existing = BlockedUser.query.filter_by(
        user_id=current_user.id,
        blocked_user_id=user_id
    ).first()
    
    if not existing:
        block = BlockedUser(user_id=current_user.id, blocked_user_id=user_id)
        db.session.add(block)
        db.session.commit()
    
    return jsonify({'success': True})

@app.route('/unblock_user/<int:user_id>', methods=['POST'])
@login_required
def unblock_user(user_id):
    block = BlockedUser.query.filter_by(
        user_id=current_user.id,
        blocked_user_id=user_id
    ).first()
    
    if block:
        db.session.delete(block)
        db.session.commit()
    
    return jsonify({'success': True})

# ── Archive Chat ──
@app.route('/archive_chat', methods=['POST'])
@login_required
def archive_chat():
    chat_type = request.json.get('chat_type')
    chat_id = request.json.get('chat_id')
    
    archive = Archive(
        user_id=current_user.id,
        chat_type=chat_type,
        chat_id=chat_id
    )
    db.session.add(archive)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/unarchive_chat', methods=['POST'])
@login_required
def unarchive_chat():
    chat_type = request.json.get('chat_type')
    chat_id = request.json.get('chat_id')
    
    archive = Archive.query.filter_by(
        user_id=current_user.id,
        chat_type=chat_type,
        chat_id=chat_id
    ).first()
    
    if archive:
        db.session.delete(archive)
        db.session.commit()
    
    return jsonify({'success': True})