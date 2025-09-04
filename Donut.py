import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import base64
import os
try:
    import pytesseract
except Exception:
    pytesseract = None
import mysql.connector
import csv
import json
import re
from datetime import datetime
from dateutil import parser
from transformers import DonutProcessor, VisionEncoderDecoderModel
import torch
import cv2
import numpy as np
from PIL import Image
# ---------- Load Donut model ----------
try:
    processor = DonutProcessor.from_pretrained("naver-clova-ix/donut-base-finetuned-docvqa")
    donut_model = VisionEncoderDecoderModel.from_pretrained("naver-clova-ix/donut-base-finetuned-docvqa")
    print("Donut model loaded successfully!")
except Exception as e:
    print("Donut model load error:", e)
    processor, donut_model = None, None


# ---------- DB connection ----------
def connect_db():
    try:
        conn = mysql.connector.connect(
            host="localhost",
            user="root",      # chỉnh user
            password="20006",  # chỉnh password
            database="labeling_db"
        )
        return conn
    except mysql.connector.Error as e:
        messagebox.showerror("DB Error", f"Database connection failed: {e}")
        return None

def preprocess_image(image_path):
    img = cv2.imread(image_path)

    # Xoay ảnh nếu bị xoay ngang (tesseract đọc dọc tốt hơn)
    img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)

    # Chuyển xám + tăng độ tương phản
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

    processed_path = image_path.replace(".png", "_proc.png")
    cv2.imwrite(processed_path, gray)
    return processed_path
# ---------- Improved Donut extractor ----------
def extract_with_donut(image_path):
    """
    Cải thiện Donut extraction với multiple prompts và better parsing
    """
    if processor is None or donut_model is None:
        return None
    
    try:
        image = Image.open(image_path).convert("RGB")
        
        # Resize image if too large for better processing
        max_size = 1280
        if max(image.size) > max_size:
            ratio = max_size / max(image.size)
            new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
            image = image.resize(new_size, Image.LANCZOS)
        
        # Try different prompts for better extraction
        prompts = [
            "<s_docvqa><s_question>What is the product name?</s_question><s_answer>",
            "<s_docvqa><s_question>What is the manufacturer company name?</s_question><s_answer>",
            "<s_docvqa><s_question>What is the manufacturing date?</s_question><s_answer>",
            "<s_docvqa><s_question>What is the expiry date?</s_question><s_answer>",
            "<s_docvqa><s_question>What is the importer company?</s_question><s_answer>",
            "<s_docvqa><s_question>What type of product is this?</s_question><s_answer>"
            "<s_docvqa><s_question>Tên sản phẩm là gì?</s_question><s_answer>",
            "<s_docvqa><s_question>Tên Công ty sản xuất là gì?</s_question><s_answer>",
            "<s_docvqa><s_question>Tên Công ty nhập khẩu là gì?</s_question><s_answer>"
            "<s_docvqa><s_question>Ngày sản xuất là ngày mấy?</s_question><s_answer>"
            "<s_docvqa><s_question>Kiểu sản phẩm là gì?</s_question><s_answer>"
        ]
        
        results = {}
        
        for i, prompt in enumerate(prompts):
            try:
                # Process with current prompt
                pixel_values = processor(image, prompt, return_tensors="pt").pixel_values
                
                # Generate answer
                outputs = donut_model.generate(
                    pixel_values,
                    max_length=256,
                    early_stopping=True,
                    pad_token_id=processor.tokenizer.pad_token_id,
                    eos_token_id=processor.tokenizer.eos_token_id,
                    use_cache=True,
                    bad_words_ids=[[processor.tokenizer.unk_token_id]],
                    return_dict_in_generate=True,
                )
                
                # Decode result
                sequence = processor.batch_decode(outputs.sequences)[0]
                sequence = sequence.replace(processor.tokenizer.eos_token, "").replace(processor.tokenizer.pad_token, "")
                sequence = re.sub(r"<.*?>", "", sequence, count=1).strip()  # remove first special token
                
                # Store result based on question type
                question_type = ["product_name", "manufacturer_company", "manufacturing_date", 
                               "expiry_date", "importer_company", "product_type"][i]
                results[question_type] = sequence
                
                print(f"Question {i+1}: {sequence}")
                
            except Exception as e:
                print(f"Error processing question {i+1}: {e}")
                continue
        
        return results
        
    except Exception as e:
        print("Donut error:", e)
        return None


# ---------- Enhanced OCR with better text extraction ----------
def extract_with_pytesseract(image_path):
    """
    Enhanced OCR extraction with better preprocessing
    """
    if pytesseract is None:
        return None
    try:
        processed_path = preprocess_image(image_path)
        image = Image.open(processed_path)

        
        # Convert to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Try different OCR configurations
        custom_config = r'--oem 3 --psm 6'  # PSM 6: single uniform block of text
        text1 = pytesseract.image_to_string(image, lang="vie+eng", config=custom_config)
        
        # Try with different PSM mode
        custom_config2 = r'--oem 3 --psm 4'  # PSM 4: single column of text
        text2 = pytesseract.image_to_string(image, lang="vie+eng", config=custom_config2)
        
        # Combine results
        combined_text = text1 + "\n\n" + text2
        
        return combined_text.strip()
    except Exception as e:
        print("pytesseract error:", e)
        return None


# ---------- Utils ----------
def validate_date(date_str):
    if not date_str:
        return True
    pattern = r"^\d{4}-\d{2}-\d{2}$"
    return re.match(pattern, date_str) is not None


def show_error(msg):
    messagebox.showerror("Validation Error", msg)


def normalize_date(date_str, output_format="%Y-%m-%d"):
    if not date_str or date_str.strip() == "":
        return ""
    try:
        # Clean the date string
        date_str = re.sub(r'[^\d/\-.]', '', date_str)
        if not date_str:
            return ""
        
        dt = parser.parse(date_str, fuzzy=True)
        return dt.strftime(output_format)
    except Exception as e:
        print(f"Date parsing error for '{date_str}': {e}")
        return ""


# ---------- Export functions ----------
def export_to_csv(filename="products.csv"):
    conn = connect_db()
    if not conn: return
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM labels")
    rows = cursor.fetchall()

    if rows:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    cursor.close()
    conn.close()
    messagebox.showinfo("Export", f"Data exported to {filename}")


def export_to_json(filename="products.json"):
    conn = connect_db()
    if not conn: return
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM labels")
    rows = cursor.fetchall()

    data = []
    for row in rows:
        data.append({
            "image_name": row["image_name"],
            "image_path": row["image_path"],
            "image_base64": row["image_base64"],
            "product_name": row["product_name"],
            "manufacturer": {
                "company_name": row["manufacturer_company"],
                "address": row["manufacturer_address"],
                "phone": row["manufacturer_phone"]
            },
            "importer": {
                "company_name": row["importer_company"],
                "address": row["importer_address"],
                "phone": row["importer_phone"]
            },
            "manufacturing_date": str(row["manufacturing_date"]) if row["manufacturing_date"] else "",
            "expiry_date": str(row["expiry_date"]) if row["expiry_date"] else "",
            "type": row["type"]
        })

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    cursor.close()
    conn.close()
    messagebox.showinfo("Export", f"Data exported to {filename}")


# ---------- GUI ----------
class ProductLabeller:
    def __init__(self, root):
        self.root = root
        self.root.title("Product Labelling App - Enhanced")
        self.root.geometry("1000x800")

        # --- Image left ---
        self.image_label = tk.Label(root, text="No image loaded", bg="lightgray")
        self.image_label.grid(row=0, column=0, rowspan=12, padx=10, pady=10, sticky="n")

        tk.Button(root, text="Load Image", command=self.load_image, bg="lightblue")\
            .grid(row=12, column=0, padx=10, pady=5, sticky="n")

        # --- Input fields right ---
        self.entries = {}
        fields = ["Product Name", "Manufacturer Company", "Manufacturer Address", "Manufacturer Phone",
                  "Importer Company", "Importer Address", "Importer Phone",
                  "Manufacturing Date (YYYY-MM-DD)", "Expiry Date (YYYY-MM-DD)", "Type"]

        row_num = 0
        for f in fields:
            tk.Label(root, text=f).grid(row=row_num, column=1, sticky="e", padx=5, pady=2)
            entry = tk.Entry(root, width=50)
            entry.grid(row=row_num, column=2, padx=5, pady=2, sticky="w")
            self.entries[f] = entry
            row_num += 1

        # --- Action buttons ---
        tk.Button(root, text="Save to DB", command=self.save_data, bg="lightgreen")\
            .grid(row=row_num, column=1, pady=10, sticky="e")
        tk.Button(root, text="Export CSV", command=lambda: export_to_csv("products.csv"), bg="lightyellow")\
            .grid(row=row_num, column=2, pady=10, sticky="w")

        row_num += 1
        tk.Button(root, text="Export JSON", command=lambda: export_to_json("products.json"), bg="lightcoral")\
            .grid(row=row_num, column=1, columnspan=2, pady=5)

        # --- Filter section ---
        tk.Label(root, text="Filter by Type").grid(row=row_num+1, column=1, sticky="e")
        self.type_var = tk.StringVar()
        self.type_dropdown = ttk.Combobox(root, textvariable=self.type_var, width=20)
        self.type_dropdown.grid(row=row_num+1, column=2, padx=5, pady=5, sticky="w")
        tk.Button(root, text="Show Products", command=self.show_products)\
            .grid(row=row_num+2, column=1, columnspan=2, pady=5)

        # --- OCR raw result box ---
        tk.Label(root, text="Extraction Results").grid(row=row_num+3, column=1, sticky="ne")
        self.ocr_box = tk.Text(root, height=8, width=70, wrap=tk.WORD)
        self.ocr_box.grid(row=row_num+3, column=2, padx=5, pady=5, sticky="w")
        
        # Add scrollbar for OCR box
        scrollbar = tk.Scrollbar(root, orient="vertical", command=self.ocr_box.yview)
        scrollbar.grid(row=row_num+3, column=3, sticky="ns", pady=5)
        self.ocr_box.configure(yscrollcommand=scrollbar.set)

        # --- Results box ---
        self.result_box = tk.Text(root, height=12, width=100, wrap=tk.WORD)
        self.result_box.grid(row=row_num+4, column=0, columnspan=4, padx=10, pady=10, sticky="ew")

        # Load types
        self.load_types()

    def _set(self, field, value):
        """Helper to set field value"""
        if value and str(value).strip():
            self.entries[field].delete(0, tk.END)
            self.entries[field].insert(0, str(value).strip())

    def autofill_from_donut(self, donut_results):
        """
        Tự động điền form từ kết quả Donut
        """
        if not donut_results or not isinstance(donut_results, dict):
            return

        try:
            # Map Donut results to form fields
            if "product_name" in donut_results:
                self._set("Product Name", donut_results["product_name"])
            
            if "manufacturer_company" in donut_results:
                self._set("Manufacturer Company", donut_results["manufacturer_company"])
            
            if "importer_company" in donut_results:
                self._set("Importer Company", donut_results["importer_company"])
            
            if "manufacturing_date" in donut_results:
                normalized_date = normalize_date(donut_results["manufacturing_date"])
                if normalized_date:
                    self._set("Manufacturing Date (YYYY-MM-DD)", normalized_date)
            
            if "expiry_date" in donut_results:
                normalized_date = normalize_date(donut_results["expiry_date"])
                if normalized_date:
                    self._set("Expiry Date (YYYY-MM-DD)", normalized_date)
            
            if "product_type" in donut_results:
                self._set("Type", donut_results["product_type"])

            print("Autofill from Donut completed successfully!")
            
        except Exception as e:
            print("Autofill from Donut error:", e)

    def autofill_from_text(self, text):
        """
        Enhanced text parsing for better field extraction
        """
        if not text:
            return
        
        try:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            text_lower = text.lower()

            # Better pattern matching
            patterns = {
                "Product Name": [
                    r"product\s*name\s*[:\-]?\s*(.+)",
                    r"tên\s*sản\s*phẩm\s*[:\-]?\s*(.+)",
                    r"name\s*[:\-]?\s*(.+)"
                ],
                "Manufacturer Company": [
                    r"manufacturer\s*[:\-]?\s*(.+)",
                    r"produced\s*by\s*[:\-]?\s*(.+)",
                    r"nhà\s*sản\s*xuất\s*[:\-]?\s*(.+)"
                ],
                "Importer Company": [
                    r"importer\s*[:\-]?\s*(.+)",
                    r"imported\s*by\s*[:\-]?\s*(.+)",
                    r"nhà\s*nhập\s*khẩu\s*[:\-]?\s*(.+)"
                ]
            }

            # Try to match patterns
            for field, field_patterns in patterns.items():
                for pattern in field_patterns:
                    match = re.search(pattern, text_lower)
                    if match:
                        value = match.group(1).strip()
                        if len(value) > 3:  # Only if meaningful length
                            self._set(field, value[:100])  # Limit length
                        break

            # Enhanced date extraction
            date_patterns = [
                r"(\d{4}[\-/\.]\d{1,2}[\-/\.]\d{1,2})",
                r"(\d{1,2}[\-/\.]\d{1,2}[\-/\.]\d{4})",
                r"(\d{1,2}/\d{1,2}/\d{2,4})",
                r"mfg\s*[:\-]?\s*(\d+[\-/\.]\d+[\-/\.]\d+)",
                r"exp\s*[:\-]?\s*(\d+[\-/\.]\d+[\-/\.]\d+)"
            ]

            all_dates = []
            for pattern in date_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                all_dates.extend(matches)

            # Normalize and assign dates
            if all_dates:
                normalized_dates = []
                for date_str in all_dates:
                    normalized = normalize_date(date_str)
                    if normalized:
                        normalized_dates.append(normalized)

                if normalized_dates:
                    # First date as manufacturing, last as expiry (if multiple)
                    self._set("Manufacturing Date (YYYY-MM-DD)", normalized_dates[0])
                    if len(normalized_dates) > 1:
                        self._set("Expiry Date (YYYY-MM-DD)", normalized_dates[-1])

            # Phone number extraction
            phone_pattern = r"(\+?\d[\d\s\-\(\)]{7,20}\d)"
            phones = re.findall(phone_pattern, text)
            if phones:
                self._set("Manufacturer Phone", phones[0][:20])
                if len(phones) > 1:
                    self._set("Importer Phone", phones[1][:20])

            print("Enhanced text parsing completed!")
            
        except Exception as e:
            print("Text parse autofill error:", e)

    def load_image(self):
        filepath = filedialog.askopenfilename(
            filetypes=[("Image files", "*.jpg *.png *.jpeg *.bmp *.gif *.tiff *.heic")]
        )
        if not filepath:
            return
            
        self.image_path = filepath
        
        try:
            img = Image.open(filepath)
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Resize for display
            max_width = 300
            w, h = img.size
            if w > max_width:
                new_height = int(h * (max_width / w))
                img = img.resize((max_width, new_height), Image.LANCZOS)

            self.imgtk = ImageTk.PhotoImage(img)
            self.image_label.config(image=self.imgtk, text="")
            self.image_label.image = self.imgtk

            # Clear previous results
            self.ocr_box.delete("1.0", tk.END)
            self.ocr_box.insert(tk.END, "Processing image...\n")
            self.root.update()

            # Process with Donut first
            donut_results = extract_with_donut(self.image_path)
            
            extraction_text = "=== DONUT RESULTS ===\n"
            filled_by_donut = False
            
            if donut_results:
                extraction_text += f"Results: {donut_results}\n\n"
                self.autofill_from_donut(donut_results)
                filled_by_donut = True
            else:
                extraction_text += "No results from Donut\n\n"

            # Fallback to OCR if Donut didn't work well
            if not filled_by_donut or not donut_results:
                extraction_text += "=== OCR FALLBACK ===\n"
                ocr_text = extract_with_pytesseract(self.image_path)
                if ocr_text:
                    extraction_text += f"OCR Text:\n{ocr_text}\n\n"
                    self.autofill_from_text(ocr_text)
                else:
                    extraction_text += "No OCR results\n"

            # Show all extraction results
            self.ocr_box.delete("1.0", tk.END)
            self.ocr_box.insert(tk.END, extraction_text)
            
            messagebox.showinfo("Success", "Image processed! Check the extracted information.")
            
        except Exception as e:
            messagebox.showerror("Error", f"Error processing image: {str(e)}")

    def save_data(self):
        try:
            # Normalize dates
            nsx = normalize_date(self.entries["Manufacturing Date (YYYY-MM-DD)"].get())
            hsd = normalize_date(self.entries["Expiry Date (YYYY-MM-DD)"].get())
            self._set("Manufacturing Date (YYYY-MM-DD)", nsx)
            self._set("Expiry Date (YYYY-MM-DD)", hsd)

            # Validate
            if not self.entries["Product Name"].get().strip():
                show_error("Product name cannot be empty.")
                return
            if nsx and not validate_date(nsx):
                show_error("Manufacturing date must be in YYYY-MM-DD format.")
                return
            if hsd and not validate_date(hsd):
                show_error("Expiry date must be in YYYY-MM-DD format.")
                return
            if not hasattr(self, "image_path"):
                show_error("No image loaded.")
                return

            # Save to database
            conn = connect_db()
            if conn is None:
                return
            cursor = conn.cursor()
            with open(self.image_path, "rb") as f:
                image_base64 = base64.b64encode(f.read()).decode("utf-8")

            data = (
                os.path.basename(self.image_path),
                self.image_path,
                image_base64,
                self.entries["Product Name"].get(),
                self.entries["Manufacturer Company"].get(),
                self.entries["Manufacturer Address"].get(),
                self.entries["Manufacturer Phone"].get(),
                self.entries["Importer Company"].get(),
                self.entries["Importer Address"].get(),
                self.entries["Importer Phone"].get(),
                nsx or None,
                hsd or None,
                self.entries["Type"].get()
            )

            query = """INSERT INTO labels
            (image_name, image_path, image_base64, product_name,
             manufacturer_company, manufacturer_address, manufacturer_phone,
             importer_company, importer_address, importer_phone,
             manufacturing_date, expiry_date, type)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""

            cursor.execute(query, data)
            conn.commit()
            cursor.close()
            conn.close()
            messagebox.showinfo("Success", "Data saved to database successfully!")

            self.load_types()
        except Exception as e:
            show_error(f"Unexpected error: {str(e)}")

    def load_types(self):
        conn = connect_db()
        if not conn: return
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT type FROM labels WHERE type IS NOT NULL AND type <> ''")
        types = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        self.type_dropdown["values"] = types

    def show_products(self):
        selected_type = self.type_var.get()
        if not selected_type:
            messagebox.showwarning("Warning", "Please select a type first!")
            return

        conn = connect_db()
        if not conn: return
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT product_name, manufacturer_company, importer_company, expiry_date FROM labels WHERE type=%s", (selected_type,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        self.result_box.delete("1.0", tk.END)
        if rows:
            self.result_box.insert(tk.END, f"Products of type '{selected_type}':\n")
            self.result_box.insert(tk.END, "="*80 + "\n\n")
            for i, r in enumerate(rows, 1):
                line = f"{i}. Product: {r['product_name']}\n"
                line += f"   Manufacturer: {r['manufacturer_company']}\n"
                line += f"   Importer: {r['importer_company']}\n"
                line += f"   Expiry: {r['expiry_date']}\n\n"
                self.result_box.insert(tk.END, line)
        else:
            self.result_box.insert(tk.END, f"No products found for type '{selected_type}'.")


if __name__ == "__main__":
    root = tk.Tk()
    app = ProductLabeller(root)
    root.mainloop()