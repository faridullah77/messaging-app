// Wait for DOM to be fully loaded
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded, initializing chat...');
    
    // Get elements
    const messageInput = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const messagesContainer = document.getElementById('messages-container');
    
    if (!messageInput) {
        console.error('message-input not found!');
        return;
    }
    if (!sendBtn) {
        console.error('send-btn not found!');
        return;
    }
    
    console.log('Elements found, setting up event listeners');
    
    // Send message function
    function sendMessage() {
        const message = messageInput.value.trim();
        console.log('Send message clicked, content:', message);
        
        if (message === '') return;
        
        if (typeof window.FRIEND_ID === 'undefined') {
            console.error('FRIEND_ID not defined!');
            alert('Error: Unable to send message');
            return;
        }
        
        console.log('Sending to friend:', window.FRIEND_ID);
        
        if (typeof socket !== 'undefined') {
            socket.emit('send_message', {
                message: message,
                receiver_id: window.FRIEND_ID,
                reply_to_id: window.currentReplyId || null
            });
            
            // Clear input
            messageInput.value = '';
            messageInput.style.height = 'auto';
            messageInput.focus();
            
            // Cancel reply if any
            if (window.cancelReply) window.cancelReply();
            
            // Stop typing indicator
            socket.emit('stop_typing', { receiver_id: window.FRIEND_ID });
        } else {
            console.error('Socket not defined!');
            alert('Connection error. Please refresh the page.');
        }
    }
    
    // Event listeners
    sendBtn.addEventListener('click', sendMessage);
    
    messageInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    messageInput.addEventListener('input', function() {
        messageInput.style.height = 'auto';
        messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
        if (typeof socket !== 'undefined') {
            socket.emit('typing', { receiver_id: window.FRIEND_ID });
            clearTimeout(window.typingTimeout);
            window.typingTimeout = setTimeout(function() {
                socket.emit('stop_typing', { receiver_id: window.FRIEND_ID });
            }, 2000);
        }
    });
    
    // Scroll to bottom function
    window.scrollToBottom = function() {
        if (messagesContainer) {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    };
    
    // Initial scroll
    window.scrollToBottom();
    
    console.log('Chat initialized successfully');
});

// Socket event handlers (defined globally)
if (typeof socket !== 'undefined') {
    socket.on('connect', function() {
        console.log('Socket connected successfully');
    });
    
    socket.on('receive_message', function(data) {
        console.log('Message received:', data);
        const messagesContainer = document.getElementById('messages-container');
        if (!messagesContainer) return;
        
        const isMine = data.sender_id === window.CURRENT_USER_ID;
        
        const msgEl = document.createElement('div');
        msgEl.classList.add('message', isMine ? 'mine' : 'theirs');
        if (data.msg_id) msgEl.dataset.msgId = data.msg_id;
        
        let contentHtml = '';
        if (data.message && data.message.startsWith('[IMAGE]')) {
            const url = data.message.slice(7, -8);
            contentHtml = `<div class="message-bubble"><img src="${url}" class="chat-image" style="max-width:200px; max-height:200px; border-radius:8px;" /></div>`;
        } else {
            contentHtml = `<div class="message-bubble" id="bubble-${data.msg_id}">${escapeHtml(data.message || '')}</div>`;
        }
        
        msgEl.innerHTML = `
            ${!isMine ? `<span class="message-sender">${escapeHtml(data.sender)}</span>` : ''}
            ${contentHtml}
            <div class="message-meta">
                <span class="message-time">${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                ${isMine ? `<span class="tick" id="tick-${data.msg_id}">✓</span>` : ''}
            </div>
        `;
        
        messagesContainer.appendChild(msgEl);
        window.scrollToBottom();
    });
}

// Helper functions
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}

function showStats() {
    if (typeof window.FRIEND_ID !== 'undefined') {
        fetch(`/stats/${window.FRIEND_ID}`)
            .then(res => res.json())
            .then(data => {
                alert(`Total Messages: ${data.total}\nYou Sent: ${data.sent}\nYou Received: ${data.received}`);
            });
    }
}