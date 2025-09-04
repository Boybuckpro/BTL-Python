import os
import re
import base64
import json
import csv
from datetime import datetime, date
from io import BytesIO
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk
import requests
import mysql.connector



# API key bạn lấy từ OCR.Space
OCR_SPACE_API_KEY = "K89633073888957"

# ---------- MySQL config ----------
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "20006",
    "database": "labeling_db"
}

# ---------- HỖ TRỢ DB ----------
def connect_db():
    return mysql.connector.connect(**DB_CONFIG)
 
def encode_image_to_base64(path):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None

def format_date_to_mysql(date_str):
    """Chuyển đổi ngày tháng về định dạng MySQL"""
    if not date_str or str(date_str).strip() == "":
        return None
    
    s = str(date_str).strip()
    # Loại bỏ các ký tự không phải số và dấu phân cách
    s = re.sub(r'[^\d\/\-\.]', '', s)
    
    patterns = [
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", 
        "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
        "%d/%m/%y", "%d-%m-%y", "%d.%m.%y"
    ]
    
    for p in patterns:
        try:
            d = datetime.strptime(s, p)
            return d.strftime("%Y-%m-%d")
        except Exception:
            pass
    
    # Tìm pattern ngày trong text
    date_patterns = [
        r"(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        r"(\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2})"
    ]
    
    for pattern in date_patterns:
        m = re.search(pattern, s)
        if m:
            return format_date_to_mysql(m.group(1))
    
    return None

# ---------- OCR VÀ TIỀN XỬ LÝ ----------
def preprocess_ocr_text(text):
    """Tiền xử lý text OCR để cải thiện độ chính xác"""
    if not text:
        return ""
    
    # Loại bỏ ký tự đặc biệt và chuẩn hóa
    text = re.sub(r'[|_]+', ' ', text)  # Thay thế | và _ bằng space
    text = re.sub(r'\s+', ' ', text)    # Loại bỏ khoảng trắng thừa
    text = re.sub(r'[^\w\s\(\)\-\+\.\,\:\;\/]', '', text, flags=re.UNICODE)  # Giữ lại ký tự cần thiết
    
    return text.strip()

def compress_image_for_ocr(image_path, max_size_kb=900):
    """Nén ảnh để phù hợp với giới hạn OCR.Space (1024 KB)"""
    try:
        from PIL import Image
        import os
        
        # Kiểm tra kích thước file hiện tại
        file_size_kb = os.path.getsize(image_path) / 1024
        if file_size_kb <= max_size_kb:
            return image_path  # Không cần nén
        
        # Mở ảnh
        img = Image.open(image_path)
        
        # Tính toán tỷ lệ nén
        quality = 95
        scale_factor = 1.0
        
        # Nếu file quá lớn, giảm kích thước
        if file_size_kb > 2000:  # Nếu > 2MB
            scale_factor = 0.7
        elif file_size_kb > 1500:  # Nếu > 1.5MB
            scale_factor = 0.8
        elif file_size_kb > 1200:  # Nếu > 1.2MB
            scale_factor = 0.9
        
        # Resize ảnh nếu cần
        if scale_factor < 1.0:
            new_width = int(img.width * scale_factor)
            new_height = int(img.height * scale_factor)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Tạo file tạm để nén
        temp_path = image_path + "_compressed.jpg"
        
        # Lưu với chất lượng thấp hơn
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        # Thử các mức chất lượng khác nhau
        for quality in [95, 90, 85, 80, 75, 70]:
            img.save(temp_path, 'JPEG', quality=quality, optimize=True)
            temp_size_kb = os.path.getsize(temp_path) / 1024
            
            if temp_size_kb <= max_size_kb:
                break
        
        return temp_path
        
    except Exception as e:
        print(f"Lỗi khi nén ảnh: {e}")
        return image_path  # Trả về file gốc nếu có lỗi

def read_text_from_image(image_path):
    """Gửi ảnh lên OCR.Space để đọc văn bản với xử lý ảnh lớn"""
    try:
        # Nén ảnh nếu cần
        compressed_path = compress_image_for_ocr(image_path)
        
        payload = {
            'isOverlayRequired': False,
            'apikey': OCR_SPACE_API_KEY,
            'language': 'vnm',     # <-- sửa ở đây: 'vnm' (3-letter code)
            'OCREngine': 2         # <-- dùng engine 2 cho tiếng Việt
        }
        
        with open(compressed_path, 'rb') as f:
            # dùng key 'file' theo docs
            r = requests.post(
                'https://api.ocr.space/parse/image',
                files={'file': f},
                data=payload,
                timeout=60
            )

        # debug: nếu còn lỗi, in status + raw response để biết chi tiết
        try:
            result = r.json()
        except Exception:
            print("OCR Space raw response:", r.status_code, r.text)
            messagebox.showerror("OCR Error", f"Lỗi khi gọi API: HTTP {r.status_code}")
            return ""

        if 'ErrorMessage' in result and result['ErrorMessage']:
           error_msg = result['ErrorMessage']
           messagebox.showerror("OCR Error", f"Lỗi từ OCR.Space: {error_msg}")
           return ""

        # Lấy text OCR từ kết quả
        parsed_results = result.get("ParsedResults")
        if parsed_results and len(parsed_results) > 0:
            return parsed_results[0].get("ParsedText", "").strip()

        return ""

    except Exception as e:
        messagebox.showerror("OCR Error", f"Lỗi khi đọc ảnh: {str(e)}")
        return ""
    finally:
        # Xóa file tạm nếu đã tạo
        if 'compressed_path' in locals() and compressed_path != image_path:
            try:
                os.remove(compressed_path)
            except:
                pass



# ---------- TRÍCH XUẤT THÔNG TIN CẢI TIẾN ----------
def extract_info(text):
    """Trích xuất thông tin với thuật toán cải tiến"""
    info = {
        "product_name": "",
        "manufacturer_name": "",
        "manufacturer_address": "",
        "manufacturer_phone": "",
        "importer_name": "",
        "importer_address": "",
        "importer_phone": "",
        "manufacturing_date": "",
        "expiry_date": "",
        "type": ""
    }

    if not text:
        return info

    # Chuẩn hóa text và tách thành lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return info

    # Enhanced patterns cho mọi loại ảnh
    phone_pattern = re.compile(r'(\+?84|0|86|\+?1)[\s\.\-\(\)]?\d{2,4}[\s\.\-\(\)]?\d{3,4}[\s\.\-\(\)]?\d{3,4}')
    date_pattern = re.compile(r'(\d{1,2}[\/\-\.\s]\d{1,2}[\/\-\.\s]\d{2,4}|\d{4}[\/\-\.\s]\d{1,2}[\/\-\.\s]\d{1,2})')
    
    # Product name patterns - improved
    product_patterns = [
        r'Thành\s*phẩm[:\s]*(.+)',
        r'Sản\s*phẩm[:\s]*(.+)',
        r'Product[:\s]*(.+)',
        r'Tên\s*sản\s*phẩm[:\s]*(.+)',
        r'Model[:\s]*(.+)',
        r'Name[:\s]*(.+)'
    ]
    
    # Universal company patterns - works with any image format
    company_patterns = [
        # Explicit Vietnamese patterns
        r'Công\s*ty\s*(?:TNHH|CP|Cổ\s*phần)[:\s]*(.+)',
        r'Công\s*ty[:\s]*(.+)',
        r'Cty[:\s]*(.+)',
        r'C\.ty[:\s]*(.+)',
        # Manufacturer specific patterns
        r'Nhà\s*sản\s*xuất[:\s]*(.+)',
        r'DVSX[:\s]*(.+)',
        r'Manufacturer[:\s]*(.+)',
        r'Made\s*by[:\s]*(.+)',
        r'Produced\s*by[:\s]*(.+)',
        r'Xuất\s*xứ[:\s]*(.+)',
        # Importer specific patterns  
        r'Nhà\s*nhập\s*khẩu\s*(?:và\s*phân\s*phối)?[:\s]*(.+)',
        r'DVNK[:\s]*(.+)',
        r'Importer[:\s]*(.+)',
        r'Distributed\s*by[:\s]*(.+)',
        r'Phân\s*phối\s*bởi[:\s]*(.+)',
        # Universal company patterns (works for any format)
        r'([A-Z\s&\.]+(?:CO|LTD|INC|CORP|LLC|JSC|LIMITED)[;\.\s,]*[^\.]*)',
        r'([A-Z][A-Z\s&\.]+(?:CO|LTD|INC|CORP|LLC)[;\.\s,]*[^\.]*)',
        r'([A-Z][a-zA-Z\s&\.]+(?:Company|Corporation|Limited|Group)[;\.\s,]*[^\.]*)',
        # Brand and trademark patterns
        r'Thương\s*hiệu[:\s]*(.+)',
        r'Brand[:\s]*(.+)',
        r'Trademark[:\s]*(.+)',
        # Generic patterns for any company format
        r'([A-Z][A-Za-z\s&\.\-]+(?:Co\.|Inc\.|Ltd\.|Corp\.|LLC)[^\.]*)',
        r'([A-Z][A-Za-z\s]+(?:\s+and\s+|\s+&\s+)[A-Z][A-Za-z\s]+(?:Co\.|Inc\.|Ltd\.|Corp\.))'
    ]
    
    # Universal address patterns - works with any image format worldwide
    address_patterns = [
        # Explicit address labels (Vietnamese)
        r'Địa\s*chỉ[:\s]*(.+)',
        r'DC[:\s]*(.+)',
        # Explicit address labels (English)  
        r'Address[:\s]*(.+)',
        r'Location[:\s]*(.+)',
        r'Site[:\s]*(.+)',
        # Universal numbered address patterns
        r'(\d+[-\s]*\d*\s*[A-Za-z\s,]+(?:Street|Road|Avenue|Lane|Drive|Boulevard|Đường|Phố|St\.|Rd\.|Ave\.).*?(?:District|City|Province|State|County|Quận|Huyện|Tỉnh|Thành|Vietnam|China|USA|UK|Japan|Korea|Thailand|Singapore|Malaysia|Indonesia))',
        r'(No\.\s*\d+.*?(?:Street|Road|Avenue|Lane|Drive|Đường|Phố|St\.|Rd\.|Ave\.).*?(?:District|City|Province|State|County|Quận|Huyện|Tỉnh|Thành|Vietnam|China|USA|UK|Japan|Korea|Thailand|Singapore|Malaysia|Indonesia))',
        r'(Room\s*\d+.*?(?:Street|Road|Avenue|Lane|Drive|Đường|Phố|St\.|Rd\.|Ave\.).*?(?:District|City|Province|State|County|Quận|Huyện|Tỉnh|Thành|Vietnam|China|USA|UK|Japan|Korea|Thailand|Singapore|Malaysia|Indonesia))',
        # Building/Floor patterns
        r'(Floor\s*\d+.*?(?:Building|Tower|Plaza).*?(?:District|City|Province|State|Vietnam|China|USA|UK|Japan|Korea|Thailand|Singapore|Malaysia|Indonesia))',
        r'(Tầng\s*\d+.*?(?:Tòa|Cao ốc|Chung cư).*?(?:Quận|Huyện|Tỉnh|Thành|Vietnam))',
        # Industrial zones and business districts
        r'([A-Z][a-z]+\s+[A-Z][a-z]+.*?(?:Industrial|Business|Economic|Technology|Park|Zone|District|City|Province|Vietnam|China|USA|UK|Japan|Korea|Thailand|Singapore|Malaysia|Indonesia))',
        # Vietnamese specific location patterns
        r'(\d+[-\s]*\d*.*?(?:Khu công nghiệp|Khu dân cư|Khu đô thị|Xã|Phường|Quận|Huyện|Tỉnh|Thành phố|TP).*?(?:Việt Nam|Vietnam))',
        # International patterns
        r'([A-Z][a-z]+[-\s]+[A-Z][a-z]+.*?(?:Tokyo|Osaka|Seoul|Bangkok|Kuala Lumpur|Jakarta|Manila|Singapore))',
        # Postal code patterns
        r'(\d+\s+[A-Za-z\s,]+\d{5,6}(?:\s+[A-Za-z]+)?)',
    ]
    
    # Universal phone patterns - works with international formats
    phone_patterns = [
        # Explicit phone labels
        r'Điện\s*thoại[:\s]*(.+)',
        r'Tel[:\s]*(.+)',
        r'Phone[:\s]*(.+)',
        r'Hotline[:\s]*(.+)',
        r'Contact[:\s]*(.+)',
        r'Mobile[:\s]*(.+)',
        r'Fax[:\s]*(.+)',
        # Universal phone number patterns (international)
        r'(\+?84[\s\.\-\(\)]?\d{2,4}[\s\.\-\(\)]?\d{3,4}[\s\.\-\(\)]?\d{3,4})',  # Vietnam
        r'(\+?86[\s\.\-\(\)]?\d{2,4}[\s\.\-\(\)]?\d{3,4}[\s\.\-\(\)]?\d{3,4})',  # China
        r'(\+?1[\s\.\-\(\)]?\d{3}[\s\.\-\(\)]?\d{3}[\s\.\-\(\)]?\d{4})',         # USA/Canada
        r'(\+?81[\s\.\-\(\)]?\d{2,4}[\s\.\-\(\)]?\d{3,4}[\s\.\-\(\)]?\d{3,4})', # Japan
        r'(\+?82[\s\.\-\(\)]?\d{2,4}[\s\.\-\(\)]?\d{3,4}[\s\.\-\(\)]?\d{3,4})', # Korea
        r'(\+?65[\s\.\-\(\)]?\d{4}[\s\.\-\(\)]?\d{4})',                          # Singapore
        r'(\+?60[\s\.\-\(\)]?\d{2,3}[\s\.\-\(\)]?\d{3,4}[\s\.\-\(\)]?\d{3,4})', # Malaysia
        r'(\+?62[\s\.\-\(\)]?\d{2,4}[\s\.\-\(\)]?\d{3,4}[\s\.\-\(\)]?\d{3,4})', # Indonesia
        r'(\+?66[\s\.\-\(\)]?\d{2,3}[\s\.\-\(\)]?\d{3,4}[\s\.\-\(\)]?\d{3,4})', # Thailand
        # Domestic patterns without country code
        r'(0[\s\.\-\(\)]?\d{2,4}[\s\.\-\(\)]?\d{3,4}[\s\.\-\(\)]?\d{3,4})',     # Domestic numbers
        r'(\d{3,4}[\s\.\-\(\)]?\d{3,4}[\s\.\-\(\)]?\d{3,4})',                   # Simple format
    ]
    
    # Universal date patterns - works with any date format
    date_patterns = [
        # Explicit date labels
        r'Ngày\s*sản\s*xuất[:\s]*(.+)',
        r'Manufacturing\s*Date[:\s]*(.+)',
        r'Mfg\s*Date[:\s]*(.+)',
        r'Produced[:\s]*(.+)',
        r'Ngày\s*hết\s*hạn[:\s]*(.+)',
        r'Expiry\s*Date[:\s]*(.+)',
        r'Exp\s*Date[:\s]*(.+)',
        r'Best\s*Before[:\s]*(.+)',
        r'Use\s*By[:\s]*(.+)',
        # Date format patterns (universal)
        r'(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',      # DD/MM/YYYY or MM/DD/YYYY
        r'(\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2})',        # YYYY/MM/DD
        r'(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})',          # DD Month YYYY
        r'([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4})',        # Month DD, YYYY
        r'(\d{2,4}\.\d{1,2}\.\d{1,2})',                   # YYYY.MM.DD
    ]

    # AGGRESSIVE extraction - xử lý từng dòng với nhiều strategy
    manufacturer_found = False
    importer_found = False
    current_section = None
    potential_companies = []
    potential_addresses = []
    potential_phones = []
    
    # Universal section detection patterns - works for any image format
    manufacturer_keywords = [
        'dvsx', 'manufacturer', 'sản xuất', 'sx', 'made by', 'produced by',
        'nhà sản xuất', 'công ty sản xuất', 'cty sx', 'mfg by', 'mfg',
        'factory', 'plant', 'production', 'xuất xứ', 'origin', 'made in',
        'manufactured in', 'produced in', 'xuất từ', 'từ', 'ĐVSX', 'sản xuất tại'
    ]
    
    importer_keywords = [
        'dvnk', 'importer', 'nhập khẩu', 'nk', 'imported by', 'distributor',
        'nhà nhập khẩu', 'công ty nhập khẩu', 'cty nk', 'phân phối',
        'đại lý', 'agent', 'representative', 'distributed by', 'sold by',
        'phân phối bởi', 'bán bởi', 'đại diện', 'ĐVNK-PP'
    ]
    
    for i, line in enumerate(lines):
        line_clean = line.strip()
        line_lower = line_clean.lower()
        
        # Enhanced section detection with better patterns
        if any(kw in line_lower for kw in manufacturer_keywords):
            current_section = 'manufacturer'
        elif any(kw in line_lower for kw in importer_keywords):
            current_section = 'importer'
        
        # Also check next few lines for context
        context_lines = []
        for j in range(max(0, i-1), min(len(lines), i+3)):
            context_lines.append(lines[j].lower())
        context_text = ' '.join(context_lines)
        
        # If current line has company info, check surrounding context
        if not current_section and any(pattern in line_lower for pattern in ['công ty', 'cty', 'company', 'corp', 'ltd', 'inc']):
            if any(kw in context_text for kw in manufacturer_keywords):
                current_section = 'manufacturer'
            elif any(kw in context_text for kw in importer_keywords):
                current_section = 'importer'
        
        # IMPROVED product name extraction first
        for pattern in product_patterns:
            match = re.search(pattern, line_clean, re.IGNORECASE)
            if match and not info["product_name"]:
                product_name = match.group(1).strip()
                product_name = re.sub(r'^[:\-\s]+|[:\-\s]+$', '', product_name)
                if len(product_name) > 3:
                    info["product_name"] = product_name
                    
        # IMPROVED company extraction with better logic
        for pattern in company_patterns:
            match = re.search(pattern, line_clean, re.IGNORECASE)
            if match:
                extracted = match.group(1).strip() if match.groups() else match.group(0).strip()
                extracted = re.sub(r'^[:\-\s]+|[:\-\s]+$', '', extracted)
                
                # Clean up extracted text - remove trailing punctuation and extra info
                extracted = re.sub(r'[;\.]+\s*$', '', extracted)
                extracted = re.sub(r'\s*Room\s*\d+.*$', lambda m: ' Room' + m.group()[4:], extracted, flags=re.IGNORECASE)
                
                if len(extracted) > 3 and extracted not in potential_companies:
                    potential_companies.append(extracted)
                    
                    # Better assignment logic based on keywords in the extracted text
                    if not manufacturer_found and current_section == 'manufacturer':
                        info["manufacturer_name"] = extracted
                        manufacturer_found = True
                    elif not importer_found and current_section == 'importer':
                        info["importer_name"] = extracted
                        importer_found = True
                    elif not manufacturer_found and not importer_found:
                        # First company found becomes manufacturer
                        info["manufacturer_name"] = extracted
                        manufacturer_found = True
                    elif manufacturer_found and not importer_found:
                        # Second company found becomes importer
                        info["importer_name"] = extracted
                        importer_found = True
        
        # IMPROVED address extraction with multi-line support
        for pattern in address_patterns:
            # For multi-line addresses, search in combined context
            search_text = line_clean
            if i < len(lines) - 2:
                # Combine current line with next 2 lines for multi-line addresses
                search_text = ' '.join([line_clean, lines[i+1].strip() if i+1 < len(lines) else '', 
                                      lines[i+2].strip() if i+2 < len(lines) else ''])
            
            match = re.search(pattern, search_text, re.IGNORECASE | re.DOTALL)
            if match:
                address = match.group(1).strip() if match.groups() else match.group(0).strip()
                address = re.sub(r'^[:\-\s]+|[:\-\s]+$', '', address)
                
                # Clean up address - remove extra punctuation
                address = re.sub(r'[;\.]+\s*$', '', address)
                
                if len(address) > 10 and address not in potential_addresses:
                    potential_addresses.append(address)
                    
                    if current_section == 'manufacturer' and not info["manufacturer_address"]:
                        info["manufacturer_address"] = address
                    elif current_section == 'importer' and not info["importer_address"]:
                        info["importer_address"] = address
                    elif not info["manufacturer_address"] and not info["importer_address"]:
                        # First address found becomes manufacturer address
                        info["manufacturer_address"] = address
                    elif info["manufacturer_address"] and not info["importer_address"]:
                        # Second address found becomes importer address
                        info["importer_address"] = address
        
        # UNIVERSAL phone extraction with multiple patterns
        for phone_pattern in phone_patterns:
            phone_match = re.search(phone_pattern, line_clean, re.IGNORECASE)
            if phone_match:
                phone = phone_match.group(1).strip() if phone_match.groups() else phone_match.group(0).strip()
                phone = re.sub(r'[\s\.\-\(\)]', '', phone)
                
                if len(phone) >= 7 and phone not in potential_phones:  # Valid phone length
                    potential_phones.append(phone)
                    
                    if current_section == 'manufacturer' and not info["manufacturer_phone"]:
                        info["manufacturer_phone"] = phone
                    elif current_section == 'importer' and not info["importer_phone"]:
                        info["importer_phone"] = phone
                    elif not info["manufacturer_phone"] and not info["importer_phone"]:
                        info["manufacturer_phone"] = phone
        
        # UNIVERSAL date extraction with multiple patterns
        for date_pattern in date_patterns:
            date_match = re.search(date_pattern, line_clean, re.IGNORECASE)
            if date_match:
                date_str = date_match.group(1).strip() if date_match.groups() else date_match.group(0).strip()
                date_str = re.sub(r'^[:\-\s]+|[:\-\s]+$', '', date_str)
                
                if len(date_str) >= 6:  # Valid date length
                    # Smart date assignment based on context
                    if any(kw in line_lower for kw in ['manufacturing', 'sản xuất', 'mfg', 'produced', 'made']):
                        if not info["manufacturing_date"]:
                            info["manufacturing_date"] = date_str
                    elif any(kw in line_lower for kw in ['expiry', 'hết hạn', 'exp', 'best before', 'use by']):
                        if not info["expiry_date"]:
                            info["expiry_date"] = date_str
                    elif not info["manufacturing_date"]:
                        info["manufacturing_date"] = date_str
                    elif not info["expiry_date"]:
                        info["expiry_date"] = date_str

    # Enhanced fallback logic for product name
    if not info["product_name"]:
        for line in lines[:5]:  # Check first 5 lines
            line_clean = line.strip()
            line_lower = line_clean.lower()
            
            # Skip obvious non-product lines
            skip_keywords = ['dvsx', 'dvnk', 'manufacturer', 'importer', 'address', 'tel', 'phone', 
                           'xuất xử', 'made in', 'room', 'no.', 'số', 'street', 'đường', 'company', 'công ty', 'model']
            if any(kw in line_lower for kw in skip_keywords):
                continue
            
            # Skip pure numbers/dates/codes
            if re.match(r'^[\d\s\-\/\.\(\)]+$', line_clean) or len(line_clean) < 5:
                continue
            
            # Look for explicit product patterns first
            for pattern in product_patterns:
                match = re.search(pattern, line_clean, re.IGNORECASE)
                if match:
                    product_name = match.group(1).strip()
                    if len(product_name) > 3:
                        info["product_name"] = product_name
                        break
            
            if info["product_name"]:
                break
                
            # Generic product name detection (improved)
            if (10 <= len(line_clean) <= 200 and 
                not any(kw in line_lower for kw in ['co', 'ltd', 'inc', 'corp', 'jsc', 'city', 'district']) and
                not re.search(r'\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2}', line_clean)):  # Not a date
                info["product_name"] = line_clean
                break

    # SMART company name filling based on order and context
    if not info["manufacturer_name"] and potential_companies:
        # Use first company as manufacturer
        info["manufacturer_name"] = potential_companies[0]
    
    if not info["importer_name"] and len(potential_companies) > 1:
        # Use second company as importer
        info["importer_name"] = potential_companies[1]
    elif not info["importer_name"] and len(potential_companies) == 1:
        # If only one company and it's different from manufacturer, use it as importer
        # Otherwise, leave importer empty (single company scenario)
        if info["manufacturer_name"] != potential_companies[0]:
            info["importer_name"] = potential_companies[0]

    # SMART address filling - match with companies if possible
    if not info["manufacturer_address"] and potential_addresses:
        info["manufacturer_address"] = potential_addresses[0]
    
    if not info["importer_address"] and len(potential_addresses) > 1:
        info["importer_address"] = potential_addresses[1]
    elif not info["importer_address"] and len(potential_addresses) == 1 and info["importer_name"]:
        # Only assign same address to importer if importer name exists and is different
        if info["importer_name"] != info["manufacturer_name"]:
            info["importer_address"] = potential_addresses[0]

    # SMART phone filling - match with companies if possible  
    if not info["manufacturer_phone"] and potential_phones:
        info["manufacturer_phone"] = potential_phones[0]
    
    if not info["importer_phone"] and len(potential_phones) > 1:
        info["importer_phone"] = potential_phones[1]
    elif not info["importer_phone"] and len(potential_phones) == 1 and info["importer_name"]:
        # Only assign same phone to importer if importer name exists and is different
        if info["importer_name"] != info["manufacturer_name"]:
            info["importer_phone"] = potential_phones[0]

    # UNIVERSAL date filling with smart extraction
    all_dates = []
    full_text = ' '.join(lines)
    for date_pattern in date_patterns:
        matches = re.findall(date_pattern, full_text, re.IGNORECASE)
        for match in matches:
            date_str = match if isinstance(match, str) else match[0] if match else ""
            if len(date_str) >= 6 and date_str not in all_dates:
                all_dates.append(date_str)
    
    if all_dates:
        if not info["manufacturing_date"]:
            info["manufacturing_date"] = all_dates[0]
        if not info["expiry_date"] and len(all_dates) > 1:
            info["expiry_date"] = all_dates[1]
        elif not info["expiry_date"] and len(all_dates) == 1:
            # If only one date found, try to determine if it's mfg or exp based on context
            date_context = full_text.lower()
            if any(kw in date_context for kw in ['exp', 'hết hạn', 'best before']):
                info["expiry_date"] = all_dates[0]
            # Otherwise keep it as manufacturing date

    # UNIVERSAL type detection - works with any product category
    if not info["type"]:
        full_text_lower = ' '.join(lines).lower()
        type_keywords = {
            'Electronics': ['điện', 'electric', 'electronic', 'power', 'voltage', 'watt', 'w', 'battery', 'charger', 'cable', 'usb', 'adapter', 'socket', 'plug'],
            'Food & Beverage': ['thực phẩm', 'food', 'nutrition', 'calorie', 'protein', 'fat', 'drink', 'beverage', 'snack', 'candy', 'chocolate', 'milk', 'coffee', 'tea'],
            
        }
        
        for type_name, keywords in type_keywords.items():
            if any(kw in full_text_lower for kw in keywords):
                info["type"] = type_name
                break
        
        if not info["type"]:
            info["type"] = "General"  # Default type

    # Post-processing để clean up data
    for key, value in info.items():
        if isinstance(value, str):
            # Loại bỏ các ký tự đặc biệt ở đầu và cuối
            value = re.sub(r'^[:\-\s\|]+|[:\-\s\|]+$', '', value)
            # Loại bỏ khoảng trắng thừa
            value = re.sub(r'\s+', ' ', value)
            info[key] = value.strip()

    return info

# ---------- LƯU DỮ LIỆU VÀ XUẤT ---------- 
def save_to_db(record):
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()

        if record and record.get("image_name"):
            sql = """
                INSERT INTO labels 
                (image_name, image_path, image_base64, product_name, manufacturer_name, manufacturer_address, 
                 manufacturer_phone, importer_name, importer_address, importer_phone, manufacturing_date, expiry_date, type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            vals = (
                record.get("image_name"),
                record.get("image_path"),
                record.get("image_base64"),
                record.get("product_name"),
                record.get("manufacturer_name"),
                record.get("manufacturer_address"),
                record.get("manufacturer_phone"),
                record.get("importer_name"),
                record.get("importer_address"),
                record.get("importer_phone"),
                record.get("manufacturing_date"),
                record.get("expiry_date"),
                record.get("type")
            )
            cursor.execute(sql, vals)
            conn.commit()
        return True, "Lưu DB thành công."
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            conn.close()

def export_json_from_db(export_json_path="labels.json"):
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM labels ORDER BY id")
        rows = cursor.fetchall()

        out = []
        for r in rows:
            man_date = r["manufacturing_date"]
            exp_date = r["expiry_date"]
            if isinstance(man_date, (datetime, date)):
                man_date = man_date.isoformat()
            if isinstance(exp_date, (datetime, date)):
                exp_date = exp_date.isoformat()
            item = {
                "id": r["id"],
                "image_name": r["image_name"],
                "image_path": r["image_path"],
                "image_base64": r["image_base64"],
                "product_name": r["product_name"],
                "manufacturer": {
                    "company_name": r["manufacturer_name"],
                    "address": r["manufacturer_address"],
                    "phone": r["manufacturer_phone"]
                },
                "importer": {
                    "company_name": r["importer_name"],
                    "address": r["importer_address"],
                    "phone": r["importer_phone"]
                },
                "manufacturing_date": man_date,
                "expiry_date": exp_date,
                "type": r["type"]
            }
            out.append(item)

        with open(export_json_path, "w", encoding="utf-8") as jf:
            json.dump(out, jf, ensure_ascii=False, indent=4)

        return True, "Xuất JSON thành công."
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            conn.close()

def save_and_export_json(record):
    ok_db, msg_db = save_to_db(record)
    if not ok_db:
        return False, f"Lỗi lưu DB: {msg_db}"

    ok_json, msg_json = export_json_from_db()
    if not ok_json:
        return False, f"Lỗi xuất JSON: {msg_json}"

    return True, "Lưu DB và xuất JSON thành công."

# ---------- GUI INTERFACE ----------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Image Labeling Tool - Improved Version")
        root.geometry("900x700")

        # Main frame
        main_frame = tk.Frame(root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Image selection
        img_frame = tk.Frame(main_frame)
        img_frame.pack(fill=tk.X, pady=5)
        tk.Label(img_frame, text="Image Path:", font=('Arial', 10, 'bold')).pack(side=tk.LEFT)
        self.entry_image_path = tk.Entry(img_frame, width=50)
        self.entry_image_path.pack(side=tk.LEFT, padx=(10,5), fill=tk.X, expand=True)
        tk.Button(img_frame, text="Chọn ảnh & OCR", command=self.choose_and_ocr, 
                 bg='lightblue').pack(side=tk.RIGHT)
        
        # File size info
        info_frame = tk.Frame(main_frame)
        info_frame.pack(fill=tk.X, pady=2)
        tk.Label(info_frame, text="💡 Tip: Ảnh sẽ được tự động nén nếu > 1MB. OCR.Space giới hạn 1MB.", 
                font=('Arial', 8), fg='gray').pack(anchor='w')

        # OCR Result display
        ocr_frame = tk.Frame(main_frame)
        ocr_frame.pack(fill=tk.X, pady=5)
        tk.Label(ocr_frame, text="OCR Result:", font=('Arial', 10, 'bold')).pack(anchor='w')
        self.text_ocr = scrolledtext.ScrolledText(ocr_frame, height=6, wrap=tk.WORD)
        self.text_ocr.pack(fill=tk.X, pady=(2,10))

        # Form fields
        form_frame = tk.Frame(main_frame)
        form_frame.pack(fill=tk.BOTH, expand=True)

        # Product
        self._create_field(form_frame, "Product Name:", 0, width=70)
        self.entry_product = self.last_entry

        # Manufacturer section
        tk.Label(form_frame, text="MANUFACTURER INFO", font=('Arial', 10, 'bold'), 
                fg='blue').grid(row=1, column=0, columnspan=3, sticky='w', pady=(10,5))
        
        self._create_field(form_frame, "Company Name:", 2, width=70)
        self.entry_manu_name = self.last_entry
        
        self._create_field(form_frame, "Address:", 3, width=70)
        self.entry_manu_addr = self.last_entry
        
        self._create_field(form_frame, "Phone:", 4, width=30)
        self.entry_manu_phone = self.last_entry

        # Importer section
        tk.Label(form_frame, text="IMPORTER INFO", font=('Arial', 10, 'bold'), 
                fg='green').grid(row=5, column=0, columnspan=3, sticky='w', pady=(10,5))
        
        self._create_field(form_frame, "Company Name:", 6, width=70)
        self.entry_imp_name = self.last_entry
        
        self._create_field(form_frame, "Address:", 7, width=70)
        self.entry_imp_addr = self.last_entry
        
        self._create_field(form_frame, "Phone:", 8, width=30)
        self.entry_imp_phone = self.last_entry

        # Dates and Type
        date_frame = tk.Frame(form_frame)
        date_frame.grid(row=9, column=0, columnspan=3, sticky='ew', pady=10)
        
        tk.Label(date_frame, text="Manufacturing Date:", font=('Arial', 9)).grid(row=0, column=0, sticky='w')
        self.entry_mfg = tk.Entry(date_frame, width=20)
        self.entry_mfg.grid(row=0, column=1, padx=5)
        
        tk.Label(date_frame, text="Expiry Date:", font=('Arial', 9)).grid(row=0, column=2, sticky='w', padx=(20,0))
        self.entry_exp = tk.Entry(date_frame, width=20)
        self.entry_exp.grid(row=0, column=3, padx=5)

        self._create_field(form_frame, "Type:", 10, width=30)
        self.entry_type = self.last_entry

        # Buttons
        btn_frame = tk.Frame(form_frame)
        btn_frame.grid(row=11, column=0, columnspan=3, pady=20)
        
        tk.Button(btn_frame, text="Save to DB", command=self.save_db_only,
         bg='lightgreen', font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=10)

        tk.Button(btn_frame, text="Export JSON", command=self.export_json_only,
         bg='lightyellow', font=('Arial', 10)).pack(side=tk.LEFT, padx=10)
        
        tk.Button(btn_frame, text="Clear Form", command=self.clear_form,
         bg='lightcoral', font=('Arial', 10)).pack(side=tk.LEFT, padx=10)

    def _create_field(self, parent, label_text, row, width=50):
        tk.Label(parent, text=label_text, font=('Arial', 9)).grid(row=row, column=0, sticky='w', pady=2)
        entry = tk.Entry(parent, width=width)
        entry.grid(row=row, column=1, columnspan=2, sticky='ew', padx=(10,0), pady=2)
        self.last_entry = entry
        return entry

    def clear_form(self):
        """Clear all form fields"""
        for widget in [self.entry_product, self.entry_manu_name, self.entry_manu_addr, 
                      self.entry_manu_phone, self.entry_imp_name, self.entry_imp_addr, 
                      self.entry_imp_phone, self.entry_mfg, self.entry_exp, self.entry_type]:
            widget.delete(0, tk.END)
        self.text_ocr.delete(1.0, tk.END)

    def choose_and_ocr(self):
        fp = filedialog.askopenfilename(
            title="Chọn ảnh",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.tiff *.gif")]
        )
        if not fp:
            return

        # Kiểm tra kích thước file
        file_size_mb = os.path.getsize(fp) / (1024 * 1024)
        if file_size_mb > 10:  # Cảnh báo nếu > 10MB
            if not messagebox.askyesno("File Size Warning", 
                f"File ảnh của bạn rất lớn ({file_size_mb:.1f} MB). "
                "Điều này có thể gây chậm và lỗi OCR. Bạn có muốn tiếp tục?"):
                return

        self.entry_image_path.delete(0, tk.END)
        self.entry_image_path.insert(0, fp)

        # Show loading message
        self.text_ocr.delete(1.0, tk.END)
        self.text_ocr.insert(tk.END, "Đang xử lý OCR...")
        self.root.update()

        try:
            ocr_text = read_text_from_image(fp)
            clean_text = preprocess_ocr_text(ocr_text)
            
            # Display OCR result
            self.text_ocr.delete(1.0, tk.END)
            self.text_ocr.insert(tk.END, ocr_text)
            
            if not ocr_text:
                messagebox.showwarning("OCR Warning", "Không trích xuất được text từ ảnh.")
                return

            # Extract information với thuật toán cải tiến
            extracted = extract_info(ocr_text)

            # Fill form với extracted data
            self.fill_form_with_extracted_data(extracted)
            
            messagebox.showinfo("Success", "OCR và trích xuất thông tin hoàn tất!")
            
        except Exception as e:
            messagebox.showerror("Error", f"Lỗi khi xử lý OCR: {str(e)}")

    def fill_form_with_extracted_data(self, extracted):
        """Fill form fields với extracted data"""
        # Product Name
        self.entry_product.delete(0, tk.END)
        self.entry_product.insert(0, extracted.get("product_name", ""))
        
        # Manufacturer Info
        self.entry_manu_name.delete(0, tk.END)
        self.entry_manu_name.insert(0, extracted.get("manufacturer_name", ""))
        
        self.entry_manu_addr.delete(0, tk.END)
        self.entry_manu_addr.insert(0, extracted.get("manufacturer_address", ""))
        
        self.entry_manu_phone.delete(0, tk.END)
        self.entry_manu_phone.insert(0, extracted.get("manufacturer_phone", ""))
        
        # Importer Info
        self.entry_imp_name.delete(0, tk.END)
        self.entry_imp_name.insert(0, extracted.get("importer_name", ""))
        
        self.entry_imp_addr.delete(0, tk.END)
        self.entry_imp_addr.insert(0, extracted.get("importer_address", ""))
        
        self.entry_imp_phone.delete(0, tk.END)
        self.entry_imp_phone.insert(0, extracted.get("importer_phone", ""))
        
        # Dates
        self.entry_mfg.delete(0, tk.END)
        self.entry_mfg.insert(0, extracted.get("manufacturing_date", ""))
        
        self.entry_exp.delete(0, tk.END)
        self.entry_exp.insert(0, extracted.get("expiry_date", ""))
        
        # Type
        self.entry_type.delete(0, tk.END)
        self.entry_type.insert(0, extracted.get("type", ""))
    
    def save_db_only(self):
        img_path = self.entry_image_path.get().strip()
        if not img_path or not os.path.exists(img_path):
           messagebox.showerror("Lỗi", "Chưa chọn ảnh hoặc đường dẫn không tồn tại.")
           return

        rec = {
          "image_name": os.path.basename(img_path),
          "image_path": img_path,
          "image_base64": encode_image_to_base64(img_path),
          "product_name": self.entry_product.get().strip(),
          "manufacturer_name": self.entry_manu_name.get().strip(),
          "manufacturer_address": self.entry_manu_addr.get().strip(),
          "manufacturer_phone": self.entry_manu_phone.get().strip(),
          "importer_name": self.entry_imp_name.get().strip(),
          "importer_address": self.entry_imp_addr.get().strip(),
          "importer_phone": self.entry_imp_phone.get().strip(),
          "manufacturing_date": format_date_to_mysql(self.entry_mfg.get().strip()),
          "expiry_date": format_date_to_mysql(self.entry_exp.get().strip()),
          "type": self.entry_type.get().strip()
        }
    

        if not rec["product_name"] or not rec["manufacturer_name"]:
           messagebox.showerror("Lỗi", "Vui lòng điền tối thiểu Product Name và Manufacturer Name.")
           return

        ok, msg = save_to_db(rec)
        if ok:
           messagebox.showinfo("Success", msg)
           self.clear_form()
        else:
           messagebox.showerror("Lỗi lưu", msg)

    def export_json_only(self):
        ok, msg = export_json_from_db(export_json_path="labels.json")
        if ok:
           messagebox.showinfo("Success", "Đã xuất labels.json từ DB")
        else:
           messagebox.showerror("Lỗi", msg)




# ---------- RUN APPLICATION ----------
if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = App(root)
        root.mainloop()
    except Exception as e:
        print(f"Lỗi khởi tạo ứng dụng: {e}")
        messagebox.showerror("Lỗi", f"Không thể khởi tạo ứng dụng: {e}")