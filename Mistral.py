import tkinter as tk
from tkinter import filedialog, messagebox
from mistralai import Mistral
from PIL import Image, ImageOps
import base64
import csv,os
import json
import mysql.connector
import pillow_heif

API_KEY = "dMVOfXXrC1IAklv4zqx6EqXRABDNaBZ6"   # thay bằng API key Mistral hợp lệ
MODEL = "mistral-large-latest"

client = Mistral(api_key=API_KEY)


# đăng ký định dạng ảnh HEIC cho Pillow
pillow_heif.register_heif_opener()

# ====== KẾT NỐI MYSQL ======
def connect_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",       # thay bằng user MySQL của bạn
        password="20006",       # thay bằng mật khẩu MySQL
        database="labeling_db"  # tạo trước database tên ocr_db
    )

def create_table():
    db = connect_db()
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_db (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ten_san_pham VARCHAR(255),
            loai_thiet_bi VARCHAR(255),
            ten_nsx VARCHAR(255),
            dia_chi_nsx TEXT,
            sdt_nsx VARCHAR(50),
            ten_nk_pp VARCHAR(255),
            dia_chi_nk_pp TEXT,
            sdt_nk_pp VARCHAR(50),
            han_su_dung VARCHAR(100)
        )
    """)
    db.commit()
    cursor.close()
    db.close()

create_table()


class OCRApp:
    def __init__(self, root):
        self.root = root
        self.root.title("OCR với Mistral AI + MySQL")

        self.entries = {}
        self.fields = [
            "Tên sản phẩm", "Loại thiết bị", "Tên NSX", "Địa chỉ NSX", "SĐT NSX",
            "Tên NK/PP", "Địa chỉ NK/PP", "SĐT NK/PP", "Hạn sử dụng"
        ]

        for i, field in enumerate(self.fields):
            tk.Label(root, text=field + ":").grid(row=i, column=0, sticky="w")
            entry = tk.Entry(root, width=50)
            entry.grid(row=i, column=1, sticky="ew", padx=5, pady=2)
            root.grid_columnconfigure(1, weight=1)
            self.entries[field] = entry

        tk.Button(root, text="Chọn ảnh", command=self.load_image).grid(row=len(self.fields), column=0, pady=10)
        tk.Button(root, text="Tự động điền bằng Mistral", command=self.autofill_mistral).grid(row=len(self.fields), column=1, pady=10)
        tk.Button(root, text="Xuất CSV", command=self.export_csv).grid(row=len(self.fields)+1, column=0, pady=10)
        tk.Button(root, text="Xuất JSON", command=self.export_json).grid(row=len(self.fields)+1, column=1, pady=10)
        tk.Button(root, text="Lưu vào MySQL", command=self.save_mysql).grid(row=len(self.fields)+2, column=0, columnspan=2, pady=10)

        self.image_base64 = None

    def load_image(self):
        file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.png;*.jpg;*.jpeg; *.heic")])
        if file_path:
           img = Image.open(file_path)

        # Tự động xoay ảnh theo EXIF (fix xoay ngang / ngược)
           img = ImageOps.exif_transpose(img)

        # Convert sang RGB (tránh lỗi với ảnh HEIC/CMYK)
           img_rgb = img.convert("RGB")

        # Lưu tạm thành JPEG để encode base64
           temp_path = "temp.jpg"
           img_rgb.save(temp_path, format="JPEG")

           with open(temp_path, "rb") as f:
              self.image_base64 = base64.b64encode(f.read()).decode("utf-8")

           messagebox.showinfo("Thông báo", "Ảnh đã được tải lên!")

    def extract_with_mistral(self, image_b64):
        prompt = """
        Trích xuất thông tin từ nhãn mác thực phẩm, trả kết quả dưới dạng JSON với các trường sau:
        - Tên sản phẩm
        - Loại thiết bị
        - Tên NSX
        - Địa chỉ NSX
        - SĐT NSX
        - Tên NK/PP
        - Địa chỉ NK/PP
        - SĐT NK/PP
        - Hạn sử dụng
        """

        response = client.chat.complete(
            model=MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]}
            ],
            response_format={"type": "json_object"}  # ép trả về JSON
        )
        return response.choices[0].message.content

    def autofill_mistral(self):
        if not self.image_base64:
            messagebox.showerror("Lỗi", "Vui lòng chọn ảnh trước!")
            return

        try:
            raw_data = self.extract_with_mistral(self.image_base64)

            data = json.loads(raw_data)

            for field in self.entries:
                value = None
                for key, val in data.items():
                    if field.replace(" ", "").lower() in key.replace(" ", "").replace("_", "").lower():
                        value = val
                        break

                if value:
                    self.entries[field].delete(0, tk.END)
                    self.entries[field].insert(0, value)

            messagebox.showinfo("Thành công", "Đã tự động điền thông tin từ Mistral!")

        except Exception as e:
            messagebox.showerror("Lỗi", f"Không gọi được API Mistral:\n{e}")

    def export_csv(self):
        try:
           conn = connect_db()
           cursor = conn.cursor()
           cursor.execute("SELECT * FROM product_results")
           rows = cursor.fetchall()

           with open("Product.csv", "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=";")
                # Ghi header
                writer.writerow([i[0] for i in cursor.description])
                # Ghi dữ liệu
                writer.writerows(rows)

           conn.close()
           messagebox.showinfo("Thành công", "Đã xuất dữ liệu từ MySQL sang CSV!")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không xuất được CSV từ MySQL:\n{e}")


    def export_json(self):

      try:
        conn = connect_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM product_results")
        records = cursor.fetchall()

        with open("Product.json", "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=4)

        conn.close()
        messagebox.showinfo("Thành công", "Đã xuất dữ liệu từ MySQL sang JSON!")
      except Exception as e:
        messagebox.showerror("Lỗi", f"Không xuất được JSON từ MySQL:\n{e}")


    def save_mysql(self):
        try:
            conn = mysql.connector.connect(
                host="localhost",
                user="root",       # đổi nếu cần
                password="20006",       # đổi nếu cần
                database="labeling_db"  # tạo sẵn DB ocr_db
            )
            cursor = conn.cursor()

            # tạo bảng nếu chưa có
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_results (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    ten_san_pham VARCHAR(255),
                    loai_thiet_bi VARCHAR(255),
                    ten_nsx VARCHAR(255),
                    dia_chi_nsx TEXT,
                    sdt_nsx VARCHAR(50),
                    ten_nkpp VARCHAR(255),
                    dia_chi_nkpp TEXT,
                    sdt_nkpp VARCHAR(50),
                    han_su_dung VARCHAR(100)
                )
            """)

            sql = """
                INSERT INTO product_results 
                (ten_san_pham, loai_thiet_bi, ten_nsx, dia_chi_nsx, sdt_nsx,
                 ten_nkpp, dia_chi_nkpp, sdt_nkpp, han_su_dung)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """
            values = [self.entries[field].get() for field in self.fields]

            cursor.execute(sql, values)
            conn.commit()
            conn.close()

            messagebox.showinfo("Thành công", "Đã lưu dữ liệu vào MySQL!")

        except Exception as e:
            messagebox.showerror("Lỗi", f"Không lưu được vào MySQL:\n{e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = OCRApp(root)
    root.mainloop()
