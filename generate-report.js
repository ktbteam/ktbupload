const fs = require('fs');
const path = require('path');

const LOG_FILE = 'upload.log';

/**
 * Đọc file upload.log cũ và trích xuất tổng số ảnh và NGÀY của log.
 * @returns {{totals: Map<string, number>, logDate: string | null}}
 */
function getPreviousTotals() {
    const totals = new Map();
    let logDate = null;

    if (!fs.existsSync(LOG_FILE)) {
        return { totals, logDate }; // File chưa tồn tại
    }

    const logContent = fs.readFileSync(LOG_FILE, 'utf8');
    const lines = logContent.split('\n');

    // Regex để tìm ngày tháng dạng YYYY-MM-DD
    const dateRegex = /^Timestamp: (\d{4}-\d{2}-\d{2})/;
    // Regex để tìm dòng thống kê
    const statsRegex = /^(.*?):.*?Total (\d+)$/;

    for (const line of lines) {
        const dateMatch = line.match(dateRegex);
        if (dateMatch) {
            logDate = dateMatch[1]; // Lấy ra chuỗi 'YYYY-MM-DD'
        }

        const statsMatch = line.match(statsRegex);
        if (statsMatch) {
            const prefix = statsMatch[1].trim();
            const totalCount = parseInt(statsMatch[2], 10);
            totals.set(prefix, totalCount);
        }
    }
    return { totals, logDate };
}

/**
 * Đọc tất cả các file *_report.txt và tính tổng số ảnh mới upload cho mỗi prefix.
 * @returns {Map<string, number>} Một Map chứa { prefix => new_count }
 */
function getNewlyUploadedCounts() {
    // ... (Hàm này giữ nguyên, không cần thay đổi) ...
    const newCounts = new Map();
    const currentDir = '.';
    const files = fs.readdirSync(currentDir);
    const reportFiles = files.filter(file => file.endsWith('_report.txt'));
    for (const file of reportFiles) {
        const reportContent = fs.readFileSync(file, 'utf8');
        const lines = reportContent.split('\n');
        for (const line of lines) {
            if (line.trim() === '') continue;
            const [prefix, countStr] = line.split(':');
            const count = parseInt(countStr, 10);
            if (prefix && !isNaN(count)) {
                const currentCount = newCounts.get(prefix.trim()) || 0;
                newCounts.set(prefix.trim(), currentCount + count);
            }
        }
    }
    return newCounts;
}


// --- Main Logic ---
function generateReport() {
    // Lấy dữ liệu cũ VÀ ngày của log cũ
    const { totals: oldTotalsFromFile, logDate } = getPreviousTotals();
    const newlyUploaded = getNewlyUploadedCounts();

    // Lấy ngày hiện tại theo múi giờ GMT+7, định dạng YYYY-MM-DD
    const currentDate = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Ho_Chi_Minh' });
    
    let previousTotals;

    // **LOGIC SO SÁNH NGÀY NẰM Ở ĐÂY**
    if (logDate === currentDate) {
        // Nếu ngày trong log trùng với ngày hiện tại -> tiếp tục cộng dồn
        console.log(`Ngày trong log (${logDate}) trùng khớp. Tiếp tục cộng dồn...`);
        previousTotals = oldTotalsFromFile;
    } else {
        // Nếu ngày khác (hoặc log không tồn tại) -> reset thống kê
        console.log(`Ngày trong log (${logDate}) khác với hôm nay (${currentDate}). Reset thống kê cho ngày mới.`);
        previousTotals = new Map();
    }


    if (newlyUploaded.size === 0 && previousTotals.size === 0) {
        // Nếu không có gì mới VÀ cũng không có gì cũ (trường hợp reset), báo thất bại
        if (!fs.existsSync(LOG_FILE) || logDate !== currentDate) {
             const options = { timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
             const timestamp = new Date().toLocaleString('en-CA', options).replace(',', '');
             fs.writeFileSync(LOG_FILE, `--- Summary of Last Upload ---\nTimestamp: ${timestamp} +0700\n\nUpload thất bại hoặc không có file mới.`);
        }
        return;
    }

    const allPrefixes = new Set([...previousTotals.keys(), ...newlyUploaded.keys()]);
    
    // Bắt đầu tạo nội dung log mới
    const options = { timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
    const timestamp = new Date().toLocaleString('en-CA', options).replace(',', '');
    let newLogContent = `--- Summary of Last Upload ---\nTimestamp: ${timestamp} +0700\n\n`;

    const sortedPrefixes = Array.from(allPrefixes).sort();

    for (const prefix of sortedPrefixes) {
        const oldTotal = previousTotals.get(prefix) || 0;
        const newCount = newlyUploaded.get(prefix) || 0;
        const currentTotal = oldTotal + newCount;

        newLogContent += `${prefix}: ${newCount} images: Total ${currentTotal}\n`;
    }

    newLogContent += `\nUpload thành công.`;

    fs.writeFileSync(LOG_FILE, newLogContent);
    console.log("Báo cáo upload.log đã được tạo thành công.");
}

generateReport();