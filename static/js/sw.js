self.addEventListener('push', function(event) {
    if (!event.data) return;

    const data = event.data.json();
    const title = data.title || 'New Message';
    const options = {
        body: data.body || '',
        icon: '/static/img/icon.png',
        badge: '/static/img/icon.png',
        vibrate: [200, 100, 200],
        data: { url: '/' }
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    event.waitUntil(
        clients.openWindow(event.notification.data.url || '/')
    );
});