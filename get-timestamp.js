function getTimestamp() {
    const date = new Date();
    
    // Sử dụng Intl.DateTimeFormat để định dạng ngày giờ theo đúng múi giờ
    const options = {
        timeZone: 'Asia/Ho_Chi_Minh',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    };

    const formatter = new Intl.DateTimeFormat('en-CA', options); // en-CA cho định dạng YYYY-MM-DD
    const parts = formatter.formatToParts(date);
    
    const partMap = {};
    for (const part of parts) {
        if (part.type !== 'literal') {
            partMap[part.type] = part.value;
        }
    }

    // Luôn trả về múi giờ +0700 cho Asia/Ho_Chi_Minh
    return `${partMap.year}-${partMap.month}-${partMap.day} ${partMap.hour}:${partMap.minute}:${partMap.second} +0700`;
}

// In ra kết quả để shell script có thể bắt được
console.log(getTimestamp());