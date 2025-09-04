import os
import re
import base64
import json
import csv
import requests
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk
import pytesseract
import tkinter.messagebox as messagebox

# MySQL
import mysql.connector

# Đường dẫn tới tesseract.exe
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ---------- CÀI ĐẶT ----------
# Nếu bạn muốn set biến môi trường trong code:
# os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "vision-key.json"


DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "20006",
    "database": "labeling_db"
}

# ---------- HỖ TRỢ ----------
def connect_db():
    return mysql.connector.connect(**DB_CONFIG)

def encode_image_to_base64(path):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None

def format_date_to_mysql(date_str):
    """
    Chuyển một số dạng ngày thường gặp về YYYY-MM-DD.
    Nếu không parse được trả về None.
    Hỗ trợ: DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD
    """
    if not date_str or date_str.strip() == "":
        return None
    date_str = date_str.strip()
    patterns = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]
    for p in patterns:
        try:
            d = datetime.strptime(date_str, p)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # thử tìm bằng regex DD/MM/YYYY hoặc YYYY-MM-DD trong chuỗi
    m = re.search(r"(\d{2}/\d{2}/\d{4})", date_str)
    if m:
        try:
            d = datetime.strptime(m.group(1), "%d/%m/%Y")
            return d.strftime("%Y-%m-%d")
        except ValueError:
            pass
    m2 = re.search(r"(\d{4}-\d{2}-\d{2})", date_str)
    if m2:
        return m2.group(1)
    return None



def read_text_from_image_pytesseract(image_path):
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang="vie+eng")  # 'vie' cho tiếng Việt
        return text.strip()
    except FileNotFoundError:
        messagebox.showerror("OCR error", f"Không tìm thấy file ảnh: {image_path}")
        return ""
    except pytesseract.TesseractNotFoundError:
        messagebox.showerror("OCR error", "Không tìm thấy Tesseract OCR.\nHãy kiểm tra lại cài đặt và PATH.")
        return ""
    except Exception as e:
        messagebox.showerror("OCR error", f"Lỗi OCR: {str(e)}")
        return ""


# ---------- TÁCH THÔNG TIN TỪ OCR ----------
def extract_info(text):
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

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # heuristic: dòng đầu có thể là tên sản phẩm
    if lines:
        info["product_name"] = lines[0]

    # tìm bằng từ khoá và regex ngày, phone
    phone_re = re.compile(r"(\+?\d[\d\-\s]{5,}\d)")
    date_re1 = re.compile(r"\d{2}/\d{2}/\d{4}")  # DD/MM/YYYY
    date_re2 = re.compile(r"\d{4}-\d{2}-\d{2}")  # YYYY-MM-DD

    for ln in lines:
        low = ln.lower()
        if "manufacturer" in low or "nsx" in low or "sản xuất" in low:
            # có thể chứa tên + địa chỉ
            if not info["manufacturer_name"]:
                info["manufacturer_name"] = ln
            elif not info["manufacturer_address"]:
                info["manufacturer_address"] = ln
        if "import" in low or "nhập khẩu" in low or "importer" in low:
            if not info["importer_name"]:
                info["importer_name"] = ln
            elif not info["importer_address"]:
                info["importer_address"] = ln

        # phone
        ph = phone_re.search(ln)
        if ph:
            num = ph.group(1).strip()
            if "nhập" in low or "import" in low:
                info["importer_phone"] = num
            elif "nsx" in low or "manufacturer" in low or "sản xuất" in low:
                info["manufacturer_phone"] = num
            else:
                # điền phone nếu chưa có
                if not info["manufacturer_phone"]:
                    info["manufacturer_phone"] = num
                elif not info["importer_phone"]:
                    info["importer_phone"] = num

        # date
        d1 = date_re1.findall(ln)
        d2 = date_re2.findall(ln)
        for d in d1 + d2:
            # Nếu chưa có mfg thì set vào manufacturing_date, nếu đã có -> expiry
            if not info["manufacturing_date"]:
                info["manufacturing_date"] = d
            elif not info["expiry_date"]:
                info["expiry_date"] = d

    return info

# ---------- LƯU DỮ LIỆU VÀ XUẤT ----------
def save_to_db_and_export_json(record, export_json_path="labels.json", export_csv_path="labels.csv"):
    """
    record: dict theo cấu trúc phù hợp
    """
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        sql = """
            INSERT INTO labels 
            (image_name, image_path, image_base64, product_name, manufacturer_name, manufacturer_address, manufacturer_phone, importer_name, importer_address, importer_phone, manufacturing_date, expiry_date, type)
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
        # Export JSON: lấy toàn bộ bảng và xuất nested JSON cho manufacturer/importer
        cursor2 = conn.cursor(dictionary=True)
        cursor2.execute("SELECT * FROM labels")
        rows = cursor2.fetchall()

        # Chuyển thành cấu trúc nested (manufacturer/importer)
        out = []
        for r in rows:
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
                "manufacturing_date": r["manufacturing_date"].isoformat() if isinstance(r["manufacturing_date"], datetime) or r["manufacturing_date"] else r["manufacturing_date"],
                "expiry_date": r["expiry_date"].isoformat() if isinstance(r["expiry_date"], datetime) or r["expiry_date"] else r["expiry_date"],
                "type": r["type"]
            }
            out.append(item)

        with open(export_json_path, "w", encoding="utf-8") as jf:
            json.dump(out, jf, ensure_ascii=False, indent=4)

        # Export CSV (flat)
        with open(export_csv_path, "w", newline="", encoding="utf-8") as cf:
            writer = csv.writer(cf)
            header = ["id","image_name","image_path","product_name","manufacturer_name","manufacturer_address","manufacturer_phone","importer_name","importer_address","importer_phone","manufacturing_date","expiry_date","type"]
            writer.writerow(header)
            for r in rows:
                writer.writerow([
                    r.get("id"),
                    r.get("image_name"),
                    r.get("image_path"),
                    r.get("product_name"),
                    r.get("manufacturer_name"),
                    r.get("manufacturer_address"),
                    r.get("manufacturer_phone"),
                    r.get("importer_name"),
                    r.get("importer_address"),
                    r.get("importer_phone"),
                    r.get("manufacturing_date"),
                    r.get("expiry_date"),
                    r.get("type")
                ])

        return True, "Lưu và xuất thành công."
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            conn.close()



# ---------- GUI & TÍCH HỢP ----------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Image Labeling Tool + OCR + MySQL + Export")

        # Image path (ẩn) và hiển thị
        tk.Label(root, text="Image Path:").grid(row=0, column=0, sticky="w")
        self.entry_image_path = tk.Entry(root, width=50)
        self.entry_image_path.grid(row=0, column=1, columnspan=3, sticky="w")

        tk.Button(root, text="Chọn ảnh & OCR", command=self.choose_and_ocr).grid(row=0, column=4)

        # Product
        tk.Label(root, text="Product Name:").grid(row=1, column=0, sticky="w")
        self.entry_product = tk.Entry(root, width=50); self.entry_product.grid(row=1, column=1, columnspan=4, sticky="w")

        # Manufacturer
        tk.Label(root, text="Manufacturer Name:").grid(row=2, column=0, sticky="w")
        self.entry_manu_name = tk.Entry(root, width=50); self.entry_manu_name.grid(row=2, column=1, columnspan=4, sticky="w")
        tk.Label(root, text="Manufacturer Address:").grid(row=3, column=0, sticky="w")
        self.entry_manu_addr = tk.Entry(root, width=50); self.entry_manu_addr.grid(row=3, column=1, columnspan=4, sticky="w")
        tk.Label(root, text="Manufacturer Phone:").grid(row=4, column=0, sticky="w")
        self.entry_manu_phone = tk.Entry(root, width=30); self.entry_manu_phone.grid(row=4, column=1, sticky="w")

        # Importer
        tk.Label(root, text="Importer Name:").grid(row=5, column=0, sticky="w")
        self.entry_imp_name = tk.Entry(root, width=50); self.entry_imp_name.grid(row=5, column=1, columnspan=4, sticky="w")
        tk.Label(root, text="Importer Address:").grid(row=6, column=0, sticky="w")
        self.entry_imp_addr = tk.Entry(root, width=50); self.entry_imp_addr.grid(row=6, column=1, columnspan=4, sticky="w")
        tk.Label(root, text="Importer Phone:").grid(row=7, column=0, sticky="w")
        self.entry_imp_phone = tk.Entry(root, width=30); self.entry_imp_phone.grid(row=7, column=1, sticky="w")

        # Dates and type
        tk.Label(root, text="Manufacturing Date (DD/MM/YYYY):").grid(row=8, column=0, sticky="w")
        self.entry_mfg = tk.Entry(root, width=20); self.entry_mfg.grid(row=8, column=1, sticky="w")
        tk.Label(root, text="Expiry Date (DD/MM/YYYY):").grid(row=8, column=2, sticky="w")
        self.entry_exp = tk.Entry(root, width=20); self.entry_exp.grid(row=8, column=3, sticky="w")

        tk.Label(root, text="Type:").grid(row=9, column=0, sticky="w")
        self.entry_type = tk.Entry(root, width=30); self.entry_type.grid(row=9, column=1, sticky="w")

        # Buttons
        tk.Button(root, text="Save to DB & Export JSON/CSV", command=self.save_and_export).grid(row=10, column=0, columnspan=2, pady=8)
        tk.Button(root, text="Export only JSON/CSV from DB", command=self.export_only).grid(row=10, column=2, columnspan=2, pady=8)

        # Extracted Info box (readable summary)
        tk.Label(root, text="Extracted Info:").grid(row=11, column=0, sticky="nw")
        self.text_summary = scrolledtext.ScrolledText(root, height=8, width=80, wrap=tk.WORD)
        self.text_summary.grid(row=11, column=1, columnspan=4, sticky="ew")

    def choose_and_ocr(self):
        fp = filedialog.askopenfilename(filetypes=[("Images", "*.png;*.jpg;*.jpeg")])
        if not fp:
            return
        self.entry_image_path.delete(0, tk.END)
        self.entry_image_path.insert(0, fp)

        try:
            ocr_text = read_text_from_image_pytesseract(fp)
        except Exception as e:
            messagebox.showerror("OCR error", str(e))
            return

        extracted = extract_info(ocr_text)
        # điền các ô
        self.entry_product.delete(0, tk.END); self.entry_product.insert(0, extracted.get("product_name",""))
        self.entry_manu_name.delete(0, tk.END); self.entry_manu_name.insert(0, extracted.get("manufacturer_name",""))
        self.entry_manu_addr.delete(0, tk.END); self.entry_manu_addr.insert(0, extracted.get("manufacturer_address",""))
        self.entry_manu_phone.delete(0, tk.END); self.entry_manu_phone.insert(0, extracted.get("manufacturer_phone",""))
        self.entry_imp_name.delete(0, tk.END); self.entry_imp_name.insert(0, extracted.get("importer_name",""))
        self.entry_imp_addr.delete(0, tk.END); self.entry_imp_addr.insert(0, extracted.get("importer_address",""))
        self.entry_imp_phone.delete(0, tk.END); self.entry_imp_phone.insert(0, extracted.get("importer_phone",""))
        self.entry_mfg.delete(0, tk.END); self.entry_mfg.insert(0, extracted.get("manufacturing_date",""))
        self.entry_exp.delete(0, tk.END); self.entry_exp.insert(0, extracted.get("expiry_date",""))

        # Cập nhật hộp thông tin tóm tắt đọc được
        try:
            summary_lines = [
                f"Product Name: {extracted.get('product_name','')}",
                f"Manufacturer Name: {extracted.get('manufacturer_name','')}",
                f"Manufacturer Address: {extracted.get('manufacturer_address','')}",
                f"Manufacturer Phone: {extracted.get('manufacturer_phone','')}",
                f"Importer Name: {extracted.get('importer_name','')}",
                f"Importer Address: {extracted.get('importer_address','')}",
                f"Importer Phone: {extracted.get('importer_phone','')}",
                f"Manufacturing Date: {extracted.get('manufacturing_date','')}",
                f"Expiry Date: {extracted.get('expiry_date','')}",
                f"Type: {extracted.get('type','')}"
            ]
            self.text_summary.delete(1.0, tk.END)
            self.text_summary.insert(tk.END, "\n".join(summary_lines))
        except Exception:
            pass

    def save_and_export(self):
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

        # Validate bắt buộc
        if not rec["product_name"] or not rec["manufacturer_name"]:
            messagebox.showerror("Lỗi", "Vui lòng điền tối thiểu Product Name và Manufacturer Name.")
            return

        ok, msg = save_to_db_and_export_json(rec)
        if ok:
            messagebox.showinfo("OK", msg)
        else:
            messagebox.showerror("Lỗi lưu", msg)

    def export_only(self):
        # chỉ gọi hàm lưu để xuất từ DB (không thêm bản ghi mới)
        ok, msg = save_to_db_and_export_json({}, export_json_path="labels.json", export_csv_path="labels.csv")
        if ok:
            messagebox.showinfo("OK", "Đã xuất labels.json và labels.csv từ DB")
        else:
            messagebox.showerror("Lỗi", msg)
    
# ---------- RUN ----------
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
