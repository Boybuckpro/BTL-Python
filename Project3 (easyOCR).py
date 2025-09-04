import os
import re
import base64
import json
import csv
from datetime import datetime, date
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk
import cv2
import easyocr
import mysql.connector

# ---------- CÀI ĐẶT EASYOCR ----------
reader = easyocr.Reader(['vi', 'en'], gpu=False)

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

def read_text_from_image_easyocr(image_path):
    try:
        # Kiểm tra file có tồn tại
        if not os.path.exists(image_path):
            messagebox.showerror("OCR error", f"Không tìm thấy file ảnh: {image_path}")
            return ""

        # Đọc ảnh bằng OpenCV
        img = cv2.imread(image_path)
        if img is None:
            messagebox.showerror("OCR error", f"Không thể mở file ảnh hoặc ảnh bị hỏng: {image_path}")
            return ""

        # Resize ảnh an toàn (chỉ khi quá lớn)
        try:
            h, w = img.shape[:2]
            max_size = 1024
            if max(h, w) > max_size:
                scale = max_size / max(h, w)
                new_w, new_h = int(w * scale), int(h * scale)
                img = cv2.resize(img, (new_w, new_h))
        except Exception as e:
            messagebox.showwarning("OCR warning", f"Không resize được ảnh, dùng ảnh gốc. Chi tiết: {str(e)}")

        # Dùng EasyOCR để nhận diện
        results = reader.readtext(img, detail=1)  # truyền img thay vì image_path

        # Lọc kết quả theo confidence
        filtered_results = []
        for (bbox, text, conf) in results:
            if conf > 0.5:  # chỉ lấy text có độ tin cậy > 50%
                filtered_results.append(text)

        text = "\n".join(filtered_results)
        return text

    except Exception as e:
        messagebox.showerror("OCR error", f"Lỗi OCR: {str(e)}")
        return ""

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

    # Chuẩn hóa text
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return info

    # Tạo index cho từng dòng
    line_info = []
    for i, line in enumerate(lines):
        line_info.append({
            'index': i,
            'original': line,
            'lower': line.lower(),
            'normalized': re.sub(r'[^\w\s]', ' ', line.lower()).strip()
        })

    # Regex patterns
    phone_pattern = re.compile(r'(\+?84|0)?[\s\-]?[1-9]\d{1,2}[\s\-]?\d{3}[\s\-]?\d{3,4}')
    date_pattern = re.compile(r'(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2})')

    # Keywords mapping với trọng số
    keywords = {
        'product_name': {
            'vi': ['tên sản phẩm', 'sản phẩm', 'ten san pham', 'Tên hàng hóa'],
            'en': ['product name', 'product', 'name'],
            'weight': 1.0
        },
        'manufacturer': {
            'vi': ['nhà sản xuất', 'công ty sản xuất', 'nha san xuat', 'nsx', 'san xuat', 'Sản xuất', 'ĐVSX', 'Nhà sản xuất - xuất khẩu'],
            'en': ['manufacturer', 'made by', 'produced by', 'mfg'],
            'weight': 1.0
        },
        'importer': {
            'vi': ['nhà nhập khẩu', 'công ty nhập khẩu', 'nhap khau', 'nk', 'ĐVNK', 'ĐVNK-PP', 'Nhà phân phối', 'Nhập khẩu & Phân phối'],
            'en': ['importer', 'imported by', 'distributor'],
            'weight': 1.0
        },
        'manufacturing_date': {
            'vi': ['ngày sản xuất', 'ngày sx', 'ngay san xuat', 'nsx', 'Tháng sản xuất', 'Năm sản xuất'],
            'en': ['manufacturing date', 'mfg date', 'production date', 'made on'],
            'weight': 1.0
        },
        'expiry_date': {
            'vi': ['hạn sử dụng', 'ngày hết hạn', 'hsd', 'han su dung', 'het han'],
            'en': ['expiry date', 'exp date', 'best before', 'use by'],
            'weight': 1.0
        },
        'address': {
            'vi': ['địa chỉ', 'dia chi', 'ĐC'],
            'en': ['address', 'addr'],
            'weight': 0.8
        },
        'phone': {
            'vi': ['điện thoại', 'dien thoai', 'dt', 'sdt', 'Điện thoại'],
            'en': ['phone', 'tel', 'mobile'],
            'weight': 0.8
        },
        'type': {
            'vi': ['loại', 'loai', 'phân loại'],
            'en': ['type', 'category'],
            'weight': 0.7
        }
    }

    def find_keyword_matches(line_lower, keyword_group):
        """Tìm keywords trong dòng text"""
        matches = []
        for lang in ['vi', 'en']:
            for kw in keyword_group.get(lang, []):
                if kw in line_lower:
                    matches.append(kw)
        return matches

    def extract_value_after_keyword(line, keyword):
        """Trích xuất giá trị sau keyword"""
        line_lower = line.lower()
        kw_pos = line_lower.find(keyword)
        if kw_pos == -1:
            return ""
        
        # Tìm dấu phân cách
        after_kw = line[kw_pos + len(keyword):]
        
        # Loại bỏ dấu phân cách đầu
        after_kw = re.sub(r'^[\s\:\-\=\>]+', '', after_kw).strip()
        
        return after_kw

    # Thu thập thông tin phones và dates
    all_phones = []
    all_dates = []
    
    for line_data in line_info:
        line = line_data['original']
        
        # Tìm phones
        phone_matches = phone_pattern.findall(line)
        for phone in phone_matches:
            cleaned_phone = re.sub(r'[\s\-\(\)]', '', phone)
            if len(cleaned_phone) >= 8:
                all_phones.append({
                    'value': cleaned_phone,
                    'line_index': line_data['index'],
                    'original_line': line
                })
        
        # Tìm dates
        date_matches = date_pattern.findall(line)
        for date_str in date_matches:
            all_dates.append({
                'value': date_str,
                'line_index': line_data['index'],
                'original_line': line
            })

    # Trích xuất từng trường thông tin
    extracted_fields = {}
    
    for line_data in line_info:
        line = line_data['original']
        line_lower = line_data['lower']
        line_index = line_data['index']
        
        # Product name
        if not extracted_fields.get('product_name'):
            matches = find_keyword_matches(line_lower, keywords['product_name'])
            if matches:
                for kw in matches:
                    value = extract_value_after_keyword(line, kw)
                    if value and len(value) > 2:
                        extracted_fields['product_name'] = value
                        break
        
        # Manufacturer
        if not extracted_fields.get('manufacturer_name'):
            matches = find_keyword_matches(line_lower, keywords['manufacturer'])
            if matches:
                for kw in matches:
                    value = extract_value_after_keyword(line, kw)
                    if value and len(value) > 2:
                        extracted_fields['manufacturer_name'] = value
                        extracted_fields['manufacturer_line'] = line_index
                        break
        
        # Importer
        if not extracted_fields.get('importer_name'):
            matches = find_keyword_matches(line_lower, keywords['importer'])
            if matches:
                for kw in matches:
                    value = extract_value_after_keyword(line, kw)
                    if value and len(value) > 2:
                        extracted_fields['importer_name'] = value
                        extracted_fields['importer_line'] = line_index
                        break
        
        # Manufacturing date
        if not extracted_fields.get('manufacturing_date'):
            matches = find_keyword_matches(line_lower, keywords['manufacturing_date'])
            if matches:
                # Tìm date trong cùng dòng hoặc dòng kế tiếp
                date_found = None
                for date_info in all_dates:
                    if abs(date_info['line_index'] - line_index) <= 1:
                        date_found = date_info['value']
                        break
                if date_found:
                    extracted_fields['manufacturing_date'] = date_found
        
        # Expiry date
        if not extracted_fields.get('expiry_date'):
            matches = find_keyword_matches(line_lower, keywords['expiry_date'])
            if matches:
                date_found = None
                for date_info in all_dates:
                    if abs(date_info['line_index'] - line_index) <= 1:
                        date_found = date_info['value']
                        break
                if date_found:
                    extracted_fields['expiry_date'] = date_found
        
        # Type
        if not extracted_fields.get('type'):
            matches = find_keyword_matches(line_lower, keywords['type'])
            if matches:
                for kw in matches:
                    value = extract_value_after_keyword(line, kw)
                    if value and len(value) > 1:
                        extracted_fields['type'] = value
                        break

    # Xử lý địa chỉ và phone dựa trên ngữ cảnh
    # Manufacturer address - tìm các dòng sau manufacturer name
    if extracted_fields.get('manufacturer_line') is not None:
        manu_line = extracted_fields['manufacturer_line']
        addr_lines = []
        for i in range(manu_line + 1, min(manu_line + 4, len(line_info))):
            line_text = line_info[i]['original']
            line_lower = line_info[i]['lower']
            
            # Dừng nếu gặp keyword khác
            if any(find_keyword_matches(line_lower, keywords[k]) for k in ['importer', 'manufacturing_date', 'expiry_date']):
                break
            
            # Bỏ qua nếu chỉ chứa phone hoặc date
            if phone_pattern.search(line_text) or date_pattern.search(line_text):
                continue
                
            addr_lines.append(line_text)
        
        if addr_lines:
            extracted_fields['manufacturer_address'] = ' '.join(addr_lines).strip()

    # Importer address
    if extracted_fields.get('importer_line') is not None:
        imp_line = extracted_fields['importer_line']
        addr_lines = []
        for i in range(imp_line + 1, min(imp_line + 4, len(line_info))):
            line_text = line_info[i]['original']
            line_lower = line_info[i]['lower']
            
            if any(find_keyword_matches(line_lower, keywords[k]) for k in ['manufacturer', 'manufacturing_date', 'expiry_date']):
                break
            
            if phone_pattern.search(line_text) or date_pattern.search(line_text):
                continue
                
            addr_lines.append(line_text)
        
        if addr_lines:
            extracted_fields['importer_address'] = ' '.join(addr_lines).strip()

    # Gán phone numbers dựa trên proximity
    if all_phones:
        manu_line = extracted_fields.get('manufacturer_line', -1)
        imp_line = extracted_fields.get('importer_line', -1)
        
        # Phân bổ phone cho manufacturer và importer
        for phone_info in all_phones:
            phone_line = phone_info['line_index']
            
            manu_dist = abs(phone_line - manu_line) if manu_line >= 0 else float('inf')
            imp_dist = abs(phone_line - imp_line) if imp_line >= 0 else float('inf')
            
            if manu_dist < imp_dist and not extracted_fields.get('manufacturer_phone'):
                extracted_fields['manufacturer_phone'] = phone_info['value']
            elif imp_dist < manu_dist and not extracted_fields.get('importer_phone'):
                extracted_fields['importer_phone'] = phone_info['value']
            elif not extracted_fields.get('manufacturer_phone'):
                extracted_fields['manufacturer_phone'] = phone_info['value']
            elif not extracted_fields.get('importer_phone'):
                extracted_fields['importer_phone'] = phone_info['value']

    # Gán dates nếu chưa có từ keywords
    if not extracted_fields.get('manufacturing_date') and all_dates:
        extracted_fields['manufacturing_date'] = all_dates[0]['value']
    
    if not extracted_fields.get('expiry_date') and len(all_dates) > 1:
        extracted_fields['expiry_date'] = all_dates[1]['value']

    # Fallback cho product name
    if not extracted_fields.get('product_name'):
        # Tìm dòng đầu tiên không chứa keywords và có độ dài hợp lý
        for line_data in line_info:
            line = line_data['original']
            line_lower = line_data['lower']
            
            # Bỏ qua dòng có keywords
            has_keywords = False
            for kw_group in keywords.values():
                if find_keyword_matches(line_lower, kw_group):
                    has_keywords = True
                    break
            
            if has_keywords:
                continue
            
            # Bỏ qua dòng chỉ có số/ngày/phone
            if re.match(r'^[\d\s\-\/\.]+$', line) or phone_pattern.search(line):
                continue
            
            # Chọn dòng có độ dài phù hợp
            if 5 <= len(line) <= 100:
                extracted_fields['product_name'] = line
                break

    # Copy vào kết quả cuối
    for key in info.keys():
        if key in extracted_fields:
            info[key] = str(extracted_fields[key]).strip()

    return info

# ---------- LƯU DỮ LIỆU VÀ XUẤT ---------- 
# Hàm lưu vào Database
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

# Hàm xuất JSON
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

        self.entry_image_path.delete(0, tk.END)
        self.entry_image_path.insert(0, fp)

        # Show loading message
        self.text_ocr.delete(1.0, tk.END)
        self.text_ocr.insert(tk.END, "Đang xử lý OCR...")
        self.root.update()

        try:
            ocr_text = read_text_from_image_easyocr(fp)
            
            # Display OCR result
            self.text_ocr.delete(1.0, tk.END)
            self.text_ocr.insert(tk.END, ocr_text)
            
            if not ocr_text:
                messagebox.showwarning("OCR Warning", "Không trích xuất được text từ ảnh.")
                return

            # Extract information
            extracted = extract_info(ocr_text)

            # Fill form with extracted data
            self.entry_product.delete(0, tk.END)
            self.entry_product.insert(0, extracted.get("product_name", ""))
            
            # Manufacturer
            self.entry_manu_name.delete(0, tk.END)
            self.entry_manu_name.insert(0, extracted.get("manufacturer_name", ""))
            self.entry_manu_addr.delete(0, tk.END)
            self.entry_manu_addr.insert(0, extracted.get("manufacturer_address", ""))
            self.entry_manu_phone.delete(0, tk.END)
            self.entry_manu_phone.insert(0, extracted.get("manufacturer_phone", ""))
            # Importer
            self.entry_imp_name.delete(0, tk.END)
            self.entry_imp_name.insert(0, extracted.get("importer_name", ""))
            self.entry_imp_addr.delete(0, tk.END)
            self.entry_imp_addr.insert(0, extracted.get("importer_address", ""))
            self.entry_imp_phone.delete(0, tk.END)
            self.entry_imp_phone.insert(0, extracted.get("importer_phone", ""))
            # Dates & Type
            self.entry_mfg.delete(0, tk.END)
            self.entry_mfg.insert(0, extracted.get("manufacturing_date", ""))
            self.entry_exp.delete(0, tk.END)
            self.entry_exp.insert(0, extracted.get("expiry_date", ""))
            self.entry_type.delete(0, tk.END)
            self.entry_type.insert(0, extracted.get("type", ""))
            
            messagebox.showinfo("Success", "OCR và trích xuất thông tin hoàn tất!")
            
        except Exception as e:
            messagebox.showerror("Error", f"Lỗi khi xử lý OCR: {str(e)}")
    
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