const fs = require('fs');
const https = require('https');

// Đọc file log với encoding utf-8, Node.js sẽ xử lý việc này rất tốt
const logContent = fs.readFileSync('upload.log', 'utf8');

// Lấy thông tin từ biến môi trường
const botToken = process.env.TELEGRAM_BOT_TOKEN;
const chatId = process.env.TELEGRAM_CHAT_ID;

if (!botToken || !chatId) {
    console.error("Lỗi: Biến môi trường TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID không tồn tại.");
    process.exit(1);
}

const payload = JSON.stringify({
    chat_id: chatId,
    text: logContent,
});

const options = {
    hostname: 'api.telegram.org',
    port: 443,
    path: `/bot${botToken}/sendMessage`,
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
    },
};

const req = https.request(options, (res) => {
    let data = '';
    res.on('data', (chunk) => {
        data += chunk;
    });
    res.on('end', () => {
        // In ra phản hồi từ Telegram để gỡ lỗi
        console.log('Phản hồi từ Telegram:', data);
        const response = JSON.parse(data);
        if (!response.ok) {
            console.error("Gửi tin nhắn Telegram thất bại.");
        }
    });
});

req.on('error', (error) => {
    console.error("Lỗi khi gửi request đến Telegram:", error);
});

req.write(payload);
req.end();