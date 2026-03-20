from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    is_online = db.Column(db.Boolean, default=False)
    avatar_url = db.Column(db.String(500), nullable=True)
    bio = db.Column(db.String(150), nullable=True)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sent_requests = db.relationship('FriendRequest', foreign_keys='FriendRequest.sender_id', backref='sender', lazy='dynamic')
    received_requests = db.relationship('FriendRequest', foreign_keys='FriendRequest.receiver_id', backref='receiver', lazy='dynamic')
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy='dynamic')
    received_messages = db.relationship('Message', foreign_keys='Message.receiver_id', backref='receiver', lazy='dynamic')

    def get_friends(self):
        sent = FriendRequest.query.filter_by(sender_id=self.id, status='accepted').all()
        received = FriendRequest.query.filter_by(receiver_id=self.id, status='accepted').all()
        friends = [r.receiver for r in sent] + [r.sender for r in received]
        return friends

    def is_friend_with(self, user):
        return FriendRequest.query.filter(
            ((FriendRequest.sender_id == self.id) & (FriendRequest.receiver_id == user.id) |
             (FriendRequest.sender_id == user.id) & (FriendRequest.receiver_id == self.id)),
            FriendRequest.status == 'accepted'
        ).first() is not None

    def has_pending_request(self, user):
        return FriendRequest.query.filter(
            ((FriendRequest.sender_id == self.id) & (FriendRequest.receiver_id == user.id) |
             (FriendRequest.sender_id == user.id) & (FriendRequest.receiver_id == self.id)),
            FriendRequest.status == 'pending'
        ).first() is not None


class FriendRequest(db.Model):
    __tablename__ = 'friend_requests'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime, nullable=True)
    is_deleted = db.Column(db.Boolean, default=False)
    is_edited = db.Column(db.Boolean, default=False)
    view_once = db.Column(db.Boolean, default=False)
    viewed = db.Column(db.Boolean, default=False)
    reply_to_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=True)
    reply_to = db.relationship('Message', remote_side=[id], backref='replies')


class Reaction(db.Model):
    __tablename__ = 'reactions'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PushSubscription(db.Model):
    __tablename__ = 'push_subscriptions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subscription_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Add these new models to your existing models.py

class Group(db.Model):
    __tablename__ = 'groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    group_photo = db.Column(db.String(500))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    members = db.relationship('GroupMember', backref='group', lazy='dynamic')
    messages = db.relationship('GroupMessage', backref='group', lazy='dynamic')

class GroupMember(db.Model):
    __tablename__ = 'group_members'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    role = db.Column(db.String(20), default='member')  # admin, member
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

class GroupMessage(db.Model):
    __tablename__ = 'group_messages'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'))
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    content = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), default='text')  # text, voice, image, video
    media_url = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, default=False)
    
class VoiceMessage(db.Model):
    __tablename__ = 'voice_messages'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'))
    audio_url = db.Column(db.String(500))
    duration = db.Column(db.Integer)  # seconds
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class BlockedUser(db.Model):
    __tablename__ = 'blocked_users'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    blocked_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Archive(db.Model):
    __tablename__ = 'archives'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    chat_type = db.Column(db.String(20))  # 'user' or 'group'
    chat_id = db.Column(db.Integer)
    archived_at = db.Column(db.DateTime, default=datetime.utcnow)

class Story(db.Model):
    __tablename__ = 'stories'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    media_url = db.Column(db.String(500))
    media_type = db.Column(db.String(20))  # image, video
    caption = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(hours=24))
    
class StoryView(db.Model):
    __tablename__ = 'story_views'
    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey('stories.id'))
    viewer_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)