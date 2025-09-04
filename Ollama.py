import os
import base64
import json
from datetime import datetime, date
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from PIL import Image, ImageTk
import mysql.connector
import easyocr
import ollama
import threading
import cv2
import numpy as np


# Ollama model to use for information extraction
OLLAMA_MODEL = "llama3.1:8b"

# MySQL config
DB_CONFIG = {
    "host": "localhost",
    "user": "root", 
    "password": "20006",
    "database": "labeling_db"
}

# Global EasyOCR reader
_ocr_reader = None
# Global EasyOCR reader (dùng CPU để ổn định, nếu muốn GPU thì đổi gpu=True)
reader = easyocr.Reader(['vi', 'en'], gpu=False)
def read_text_from_image_simple(image_path):
    try:
        if not os.path.exists(image_path):
            print(f"OCR error: file not found {image_path}")
            return ""

        img = cv2.imread(image_path)
        if img is None:
            print(f"OCR error: cannot open {image_path}")
            return ""

        # Resize nếu quá lớn
        h, w = img.shape[:2]
        max_size = 1024
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            img = cv2.resize(img, (new_w, new_h))

        # OCR với EasyOCR
        results = reader.readtext(img, detail=1)
        filtered = [text for (bbox, text, conf) in results if conf > 0.5]

        return "\n".join(filtered)

    except Exception as e:
        print(f"OCR error: {e}")
        return ""
def get_ocr_reader():
    """Get or initialize EasyOCR reader"""
    global _ocr_reader
    if _ocr_reader is None:
        try:
            _ocr_reader = easyocr.Reader(['vi', 'en'], gpu=True)
            print("EasyOCR initialized with GPU")
        except Exception as e:
            print(f"GPU failed, using CPU: {e}")
            _ocr_reader = easyocr.Reader(['vi', 'en'], gpu=False)
            print("EasyOCR initialized with CPU")
    return _ocr_reader

# ---------- Database helpers ----------
def connect_db():
    return mysql.connector.connect(**DB_CONFIG)

def encode_image_to_base64(path):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None

def format_date_to_mysql(date_str):
    """Convert date string to MySQL format"""
    if not date_str or str(date_str).strip() == "":
        return None
    
    s = str(date_str).strip()
    patterns = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y", "%Y"]
    
    # Clean the string
    import re
    s = re.sub(r'[^\d\/\-\.\s]', '', s)
    s = re.sub(r'\s+', '', s)
    
    # Try year only pattern first
    year_match = re.search(r'\b(20\d{2})\b', s)
    if year_match and len(s.strip()) == 4:
        return f"{year_match.group(1)}-01-01"
    
    for p in patterns:
        try:
            d = datetime.strptime(s, p)
            return d.strftime("%Y-%m-%d")
        except:
            continue
    
    return None

# ---------- Simplified OCR ----------
def read_text_from_image_simple(image_path):
    """Simplified OCR without complex preprocessing"""
    try:
        if not os.path.exists(image_path):
            print(f"OCR error: file not found {image_path}")
            return ""

        img = cv2.imread(image_path)
        if img is None:
            print(f"OCR error: cannot open {image_path}")
            return ""

        # Resize nếu quá lớn
        h, w = img.shape[:2]
        max_size = 1024
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            img = cv2.resize(img, (new_w, new_h))

        # OCR với EasyOCR
        results = reader.readtext(img, detail=1)
        filtered = [text for (bbox, text, conf) in results if conf > 0.5]

        return "\n".join(filtered)

    except Exception as e:
        print(f"OCR error: {e}")
        return ""

# ---------- Optimized Ollama extraction ----------
def extract_info_with_ollama_optimized(ocr_text, model=OLLAMA_MODEL):
    """Optimized Ollama extraction with improved JSON parsing"""
    if not ocr_text or not ocr_text.strip():
        print("No OCR text to process")
        return create_empty_result()

    # Simplified and more effective system prompt
    system_prompt = """You are an AI assistant that extracts product information from Vietnamese product labels.

Extract information from the OCR text and return ONLY a JSON object with these exact keys:
- product_name: Product name or brand
- manufacturer_name: Manufacturing company name  
- manufacturer_address: Manufacturing company address
- manufacturer_phone: Manufacturing company phone
- importer_name: Import company name (Vietnamese company)
- importer_address: Import company address (Vietnamese address)
- importer_phone: Import company phone
- manufacturing_date: Manufacturing date or year
- expiry_date: Expiry date
- type: Product type or category

Important rules:
- Return ONLY the JSON object, no other text
- Use empty string "" for missing information
- Keep original text from OCR, don't translate
- Include full company names and addresses exactly as shown"""

    user_prompt = f"Extract product information from this text:\n\n{ocr_text}"

    try:
        print(f"Sending request to Ollama model: {model}")
        
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            options={
                "temperature": 0.1,
                "top_p": 0.9,
                "num_predict": 500,
                "repeat_penalty": 1.0
            }
        )

        content = response.get("message", {}).get("content", "").strip()
        print(f"Ollama response received, length: {len(content)}")
        
        if not content:
            print("Empty response from Ollama")
            return create_empty_result()

        # Improved JSON parsing
        json_data = parse_json_from_response(content)
        
        if json_data:
            # Validate and clean the extracted data
            cleaned_data = clean_extracted_data(json_data)
            cleaned_data["_extraction_method"] = "ollama"
            print("Successfully extracted data with Ollama")
            return cleaned_data
        else:
            print("Failed to parse JSON from Ollama response")
            print(f"Raw response: {content[:200]}...")
            return create_empty_result()
            
    except Exception as e:
        print(f"Ollama extraction error: {e}")
        return create_empty_result()

def parse_json_from_response(content):
    """Improved JSON parsing from Ollama response"""
    try:
        # First try: Direct JSON parsing
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    # Second try: Find JSON in response text
    import re
    
    # Look for JSON object patterns
    json_patterns = [
        r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',  # Nested braces
        r'\{.*?\}',  # Simple braces
    ]
    
    for pattern in json_patterns:
        matches = re.findall(pattern, content, re.DOTALL)
        for match in matches:
            try:
                # Clean the match
                cleaned = match.strip()
                
                # Try to parse
                data = json.loads(cleaned)
                if isinstance(data, dict) and len(data) > 0:
                    return data
                    
            except json.JSONDecodeError:
                continue
    
    # Third try: Extract key-value pairs manually
    try:
        return extract_key_value_pairs(content)
    except:
        pass
    
    return None

def extract_key_value_pairs(content):
    """Manually extract key-value pairs if JSON parsing fails"""
    import re
    
    result = {}
    expected_keys = [
        "product_name", "manufacturer_name", "manufacturer_address", 
        "manufacturer_phone", "importer_name", "importer_address", 
        "importer_phone", "manufacturing_date", "expiry_date", "type"
    ]
    
    for key in expected_keys:
        # Look for patterns like "key": "value"
        patterns = [
            rf'"{key}"\s*:\s*"([^"]*)"',
            rf'"{key}"\s*:\s*([^,\n\}}]+)',
            rf'{key}\s*:\s*"([^"]*)"',
            rf'{key}\s*:\s*([^,\n\}}]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
            if match:
                value = match.group(1).strip().strip('"').strip("'")
                result[key] = value
                break
        
        if key not in result:
            result[key] = ""
    
    return result if any(result.values()) else None

def clean_extracted_data(data):
    """Clean and validate extracted data"""
    expected_keys = [
        "product_name", "manufacturer_name", "manufacturer_address", 
        "manufacturer_phone", "importer_name", "importer_address", 
        "importer_phone", "manufacturing_date", "expiry_date", "type"
    ]
    
    cleaned = {}
    for key in expected_keys:
        value = str(data.get(key, "")).strip()
        
        # Remove unwanted values
        unwanted = ['null', 'none', 'n/a', 'unknown', 'không có', 'không rõ', 'không xác định']
        if value.lower() in unwanted:
            value = ""
        
        # Remove extra quotes
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        
        # Limit length
        cleaned[key] = value[:500] if value else ""
    
    return cleaned

def create_empty_result():
    """Create empty result structure"""
    empty_result = {
        "product_name": "",
        "manufacturer_name": "",
        "manufacturer_address": "",
        "manufacturer_phone": "",
        "importer_name": "",
        "importer_address": "",
        "importer_phone": "",
        "manufacturing_date": "",
        "expiry_date": "",
        "type": "",
        "_extraction_method": "failed"
    }
    return empty_result

# ---------- Database operations ----------
def save_to_db(record):
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()

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
        return True, "LÆ°u DB thÃ nh cÃ´ng."
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
            json.dump(out, jf, ensure_ascii=False, indent=2)

        return True, "Xuất JSON thành công."
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            conn.close()

# ---------- Simplified GUI Application ----------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Enhanced Image Labeling Tool - OCR + AI Extraction")
        root.geometry("1200x900")

        # Main frame with scrolling
        self.main_canvas = tk.Canvas(root)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=self.main_canvas.yview)
        self.scrollable_frame = ttk.Frame(self.main_canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))
        )

        self.main_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.main_canvas.configure(yscrollcommand=scrollbar.set)

        main_frame = tk.Frame(self.scrollable_frame)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        # Title section
        title_frame = tk.Frame(main_frame)
        title_frame.pack(fill=tk.X, pady=(0, 15))
        
        title_label = tk.Label(title_frame, text="Enhanced OCR + AI Extraction Tool", 
                              font=('Arial', 16, 'bold'), fg='darkblue')
        title_label.pack(side=tk.LEFT)
        
        self.status_label = tk.Label(title_frame, text="Initializing...", 
                                   font=('Arial', 11), fg='orange')
        self.status_label.pack(side=tk.RIGHT)

        # Image section
        img_section = tk.LabelFrame(main_frame, text="Image Processing", 
                                   font=('Arial', 11, 'bold'), fg='darkgreen')
        img_section.pack(fill=tk.X, pady=(0, 10))

        img_controls = tk.Frame(img_section)
        img_controls.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(img_controls, text="Image Path:", font=('Arial', 10, 'bold')).pack(side=tk.LEFT)
        self.entry_image_path = tk.Entry(img_controls, width=50, font=('Arial', 10))
        self.entry_image_path.pack(side=tk.LEFT, padx=(10,5), fill=tk.X, expand=True)
        
        # Add load button for existing path
        self.btn_load = tk.Button(img_controls, text="Load", 
                                command=self.load_existing_image, bg='lightgreen', 
                                font=('Arial', 10), cursor='hand2', width=8)
        self.btn_load.pack(side=tk.RIGHT, padx=(5,5))
        
        self.btn_ocr = tk.Button(img_controls, text="Select & Analyze", 
                                command=self.choose_and_process, bg='lightblue', 
                                font=('Arial', 10, 'bold'), cursor='hand2')
        self.btn_ocr.pack(side=tk.RIGHT, padx=(5,0))

        # Image preview section
        img_preview_frame = tk.Frame(img_section)
        img_preview_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Create image display label
        self.image_label = tk.Label(img_preview_frame, text="No image selected", 
                                   bg='#f0f0f0', relief='sunken', width=60, height=15)
        self.image_label.pack(side=tk.LEFT, padx=(0,10))
        
        # Image info frame
        img_info_frame = tk.Frame(img_preview_frame)
        img_info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.img_info_label = tk.Label(img_info_frame, text="Image Information:\nNo image loaded", 
                                      font=('Arial', 9), justify=tk.LEFT, anchor='nw')
        self.img_info_label.pack(fill=tk.BOTH, expand=True)

        # Progress section
        progress_frame = tk.Frame(img_section)
        progress_frame.pack(fill=tk.X, padx=10, pady=(0,10))
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, 
                                          maximum=100, length=400)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.progress_label = tk.Label(progress_frame, text="Ready", font=('Arial', 9))
        self.progress_label.pack(side=tk.RIGHT, padx=(10,0))

        # OCR Results section
        ocr_section = tk.LabelFrame(main_frame, text="OCR Extracted Text", 
                                   font=('Arial', 11, 'bold'), fg='darkred')
        ocr_section.pack(fill=tk.X, pady=(0, 10))
        
        self.text_ocr = scrolledtext.ScrolledText(ocr_section, height=8, wrap=tk.WORD, 
                                                font=('Consolas', 9), bg='#f8f8f8')
        self.text_ocr.pack(fill=tk.X, padx=10, pady=10)

        # Create all form fields
        self._create_form_fields(main_frame)

        # Action buttons
        self._create_action_buttons(main_frame)

        # Pack scrolling components
        self.main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind mousewheel
        self._bind_mousewheel()

        # Initialize OCR
        self.init_ocr_reader()
        
        # Initialize image-related variables
        self.current_image = None
        self.original_image_size = None

    def load_existing_image(self):
        """Load image from existing path in entry field"""
        image_path = self.entry_image_path.get().strip()
        if not image_path:
            messagebox.showwarning("Warning", "Please enter an image path first.")
            return
            
        success = self.display_image_preview(image_path)
        if success:
            self.status_label.config(text="Image loaded successfully", fg='green')
        else:
            messagebox.showerror("Error", "Failed to load image. Check the path and try again.")

    def display_image_preview(self, image_path):
        """Display image preview with information and better error handling"""
        try:
            print(f"Attempting to load image: {image_path}")
            
            # Check if file exists and is readable
            if not os.path.exists(image_path):
                raise Exception(f"File not found: {image_path}")
                
            if not os.path.isfile(image_path):
                raise Exception(f"Path is not a file: {image_path}")
                
            # Check file size
            file_size = os.path.getsize(image_path) / 1024  # KB
            if file_size == 0:
                raise Exception("File is empty")
            
            print(f"File size: {file_size:.1f} KB")
            
            # Try to open image
            try:
                img = Image.open(image_path)
                print(f"Image loaded successfully: {img.format}, {img.size}, {img.mode}")
            except Exception as e:
                raise Exception(f"Cannot open image file: {str(e)}")
            
            # Store original image info
            self.current_image = img.copy()
            self.original_image_size = img.size
            img_format = img.format if img.format else "Unknown"
            
            # Create thumbnail for display (maintain aspect ratio)
            display_size = (280, 180)
            img_display = img.copy()
            img_display.thumbnail(display_size, Image.Resampling.LANCZOS)
            print(f"Thumbnail created: {img_display.size}")
            
            # Convert to PhotoImage
            try:
                photo = ImageTk.PhotoImage(img_display)
                print("PhotoImage created successfully")
            except Exception as e:
                raise Exception(f"Cannot create PhotoImage: {str(e)}")
            
            # Update image label
            self.image_label.config(
                image=photo, 
                text="", 
                bg='white',
                relief='sunken',
                borderwidth=2
            )
            self.image_label.image = photo  # Keep reference to prevent garbage collection
            
            # Update image info
            info_text = f"""Image Information:
Filename: {os.path.basename(image_path)}
Format: {img_format}
Dimensions: {self.original_image_size[0]} x {self.original_image_size[1]} pixels
File Size: {file_size:.1f} KB
Color Mode: {img.mode}
Status: Ready for processing"""
            
            self.img_info_label.config(text=info_text, fg='darkgreen')
            
            print(f"Image preview loaded successfully: {os.path.basename(image_path)}")
            return True
            
        except Exception as e:
            error_msg = str(e)
            print(f"Error loading image preview: {error_msg}")
            
            # Show error in image preview
            self.image_label.config(
                image="", 
                text=f"Error loading image:\n{error_msg}", 
                fg='red', 
                bg='#ffeeee',
                compound='center',
                justify='center'
            )
            self.image_label.image = None
            
            # Show error in info panel
            self.img_info_label.config(
                text=f"Image Error:\n{error_msg}\n\nPlease select a valid image file.",
                fg='red'
            )
            
            # Also show in status
            self.status_label.config(text="Image load failed", fg='red')
            return False

    def clear_image_preview(self):
        """Clear image preview"""
        self.image_label.config(
            image="", 
            text="No image selected", 
            fg='gray',
            bg='#f0f0f0',
            compound='center',
            justify='center'
        )
        self.image_label.image = None
        self.img_info_label.config(text="Image Information:\nNo image loaded", fg='black')
        self.current_image = None
        self.original_image_size = None
        print("Image preview cleared")

    def _create_form_fields(self, parent):
        """Create all form fields"""
        results_section = tk.LabelFrame(parent, text="Extracted Information", 
                                       font=('Arial', 12, 'bold'), fg='darkblue')
        results_section.pack(fill=tk.BOTH, expand=True)

        # Product section
        product_frame = tk.LabelFrame(results_section, text="Product Information", 
                                     font=('Arial', 10, 'bold'), fg='purple')
        product_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self._create_field(product_frame, "Product Name:", 0, width=80)
        self.entry_product = self.last_entry

        # Manufacturer section
        manu_frame = tk.LabelFrame(results_section, text="Manufacturer Information", 
                                  font=('Arial', 10, 'bold'), fg='blue')
        manu_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self._create_field(manu_frame, "Company Name:", 0, width=80)
        self.entry_manu_name = self.last_entry
        
        self._create_field(manu_frame, "Address:", 1, width=80)
        self.entry_manu_addr = self.last_entry
        
        self._create_field(manu_frame, "Phone:", 2, width=80)
        self.entry_manu_phone = self.last_entry

        # Importer section
        imp_frame = tk.LabelFrame(results_section, text="Importer Information", 
                                 font=('Arial', 10, 'bold'), fg='green')
        imp_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self._create_field(imp_frame, "Company Name:", 0, width=80)
        self.entry_imp_name = self.last_entry
        
        self._create_field(imp_frame, "Address:", 1, width=80)
        self.entry_imp_addr = self.last_entry
        
        self._create_field(imp_frame, "Phone:", 2, width=80)
        self.entry_imp_phone = self.last_entry

        # Dates and Type section
        misc_frame = tk.LabelFrame(results_section, text="Dates & Classification", 
                                  font=('Arial', 10, 'bold'), fg='darkorange')
        misc_frame.pack(fill=tk.X, padx=10, pady=5)
        
        date_row = tk.Frame(misc_frame)
        date_row.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(date_row, text="Manufacturing Date:", font=('Arial', 10)).pack(side=tk.LEFT)
        self.entry_mfg = tk.Entry(date_row, width=25, font=('Arial', 10))
        self.entry_mfg.pack(side=tk.LEFT, padx=(10, 20))
        
        tk.Label(date_row, text="Expiry Date:", font=('Arial', 10)).pack(side=tk.LEFT)
        self.entry_exp = tk.Entry(date_row, width=25, font=('Arial', 10))
        self.entry_exp.pack(side=tk.LEFT, padx=(10, 0))

        type_row = tk.Frame(misc_frame)
        type_row.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(type_row, text="Product Type:", font=('Arial', 10)).pack(side=tk.LEFT)
        self.entry_type = tk.Entry(type_row, width=60, font=('Arial', 10))
        self.entry_type.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)

    def _create_action_buttons(self, parent):
        """Create action buttons"""
        btn_frame = tk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=15)
        
        btn_style = {'font': ('Arial', 11, 'bold'), 'cursor': 'hand2', 'relief': 'raised'}
        
        tk.Button(btn_frame, text="Save to Database", command=self.save_db_only,
                 bg='#90EE90', **btn_style).pack(side=tk.LEFT, padx=15)

        tk.Button(btn_frame, text="Export JSON", command=self.export_json_only,
                 bg='#FFD700', **btn_style).pack(side=tk.LEFT, padx=15)
        
        tk.Button(btn_frame, text="Clear Form", command=self.clear_form,
                 bg='#FFB6C1', **btn_style).pack(side=tk.LEFT, padx=15)

    def _bind_mousewheel(self):
        def _on_mousewheel(event):
            self.main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.main_canvas.bind("<MouseWheel>", _on_mousewheel)

    def init_ocr_reader(self):
        """Initialize OCR reader in background"""
        def init_reader():
            try:
                self.status_label.config(text="Loading OCR Engine...", fg='blue')
                get_ocr_reader()
                self.status_label.config(text="OCR Ready", fg='green')
                print("EasyOCR reader initialized successfully")
            except Exception as e:
                self.status_label.config(text="OCR Init Failed", fg='red')
                print(f"EasyOCR initialization failed: {e}")
        
        threading.Thread(target=init_reader, daemon=True).start()

    def _create_field(self, parent, label_text, row, width=60):
        field_frame = tk.Frame(parent)
        field_frame.pack(fill=tk.X, padx=10, pady=3)
        
        label = tk.Label(field_frame, text=label_text, font=('Arial', 10), width=15, anchor='w')
        label.pack(side=tk.LEFT)
        
        entry = tk.Entry(field_frame, width=width, font=('Arial', 10))
        entry.pack(side=tk.LEFT, padx=(10,0), fill=tk.X, expand=True)
        
        self.last_entry = entry
        return entry

    def clear_form(self):
        """Clear all form fields and image preview"""
        if messagebox.askyesno("Xác nhận", "Bạn có chắc muốn thoát và đặt lại tất cả dữ liệu?"):
            for widget in [self.entry_product, self.entry_manu_name, self.entry_manu_addr, 
                          self.entry_manu_phone, self.entry_imp_name, self.entry_imp_addr, 
                          self.entry_imp_phone, self.entry_mfg, self.entry_exp, self.entry_type]:
                widget.delete(0, tk.END)
            self.text_ocr.delete(1.0, tk.END)
            self.entry_image_path.delete(0, tk.END)
            
            # Clear image preview
            self.clear_image_preview()
            
            self.progress_var.set(0)
            self.progress_label.config(text="Ready")
            self.status_label.config(text="Form Cleared", fg='green')

    def update_progress(self, value, message=None):
        """Update progress bar"""
        self.progress_var.set(value)
        if message:
            self.progress_label.config(text=message)
            self.status_label.config(text=f"{message}", fg='blue')
        self.root.update_idletasks()

    def choose_and_process(self):
        """Image selection and processing with preview"""
        fp = filedialog.askopenfilename(
            title="Chọn ảnh sản phẩm",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.tiff *.gif"),
                ("JPEG files", "*.jpg *.jpeg"),
                ("PNG files", "*.png"),
                ("All files", "*.*")
            ]
        )
        if not fp:
            return

        # Update path and display image preview immediately
        self.entry_image_path.delete(0, tk.END)
        self.entry_image_path.insert(0, fp)
        
        # Display image preview first
        success = self.display_image_preview(fp)
        if not success:
            self.status_label.config(text="Image load failed - check console", fg='red')
            return

        # Process in separate thread
        def process_image():
            try:
                self.btn_ocr.config(state='disabled', text="Đang xử lý...")
                self.status_label.config(text="Starting processing...", fg='blue')
                
                # Step 1: Validate image
                self.update_progress(10, "Validating image...")
                if not os.path.exists(fp):
                    raise Exception("File không tồn tại")
                
                file_size = os.path.getsize(fp)
                if file_size == 0:
                    raise Exception("File rỗng")
                    
                if file_size > 50 * 1024 * 1024:  # 50MB limit
                    raise Exception("File quá lớn (>50MB)")
                
                # Step 2: OCR Processing
                self.update_progress(30, "Running OCR...")
                ocr_text = read_text_from_image_simple(fp)
                
                # Display OCR result
                self.root.after(0, lambda: self._update_ocr_display(ocr_text))
                
                if not ocr_text or len(ocr_text.strip()) < 3:
                    self.update_progress(50, "OCR completed - limited text")
                    messagebox.showwarning("Cảnh báo", "Không tìm thấy ký tự văn bản trong ảnh.")
                else:
                    self.update_progress(60, f"OCR completed - {len(ocr_text)} chars")

                # Step 3: AI Extraction
                self.update_progress(75, "AI analyzing...")
                extracted = extract_info_with_ollama_optimized(ocr_text)

                # Step 4: Fill form
                self.update_progress(95, "Filling form...")
                self.root.after(0, lambda: self.fill_form_with_extracted_data(extracted))
                
                # Step 5: Complete
                self.update_progress(100, "Processing completed!")
                
                # Show results
                method = extracted.get("_extraction_method", "unknown")
                if method == "ollama":
                    self.status_label.config(text="AI extraction successful", fg='green')
                    filled_fields = sum(1 for k, v in extracted.items() 
                                      if not k.startswith("_") and v and v.strip())
                    messagebox.showinfo("Thành Công", 
                                      f"Trích xuất thành công!\nĐã điền {filled_fields}/10 trường thông tin")
                else:
                    self.status_label.config(text="AI extraction failed", fg='red')
                    messagebox.showwarning("Thất bại", "AI không thể trích xuất thông tin")
                
            except Exception as e:
                self.status_label.config(text="Processing failed", fg='red')
                error_msg = str(e)
                print(f"Processing error: {error_msg}")
                messagebox.showerror("Lỗi xử lý", f"Đã xảy ra lỗi khi xử lý:\n\n{error_msg}")
            finally:
                self.btn_ocr.config(state='normal', text="Select & Analyze")
                self.root.after(3000, lambda: self.progress_var.set(0))
                self.root.after(3000, lambda: self.progress_label.config(text="Ready"))

        threading.Thread(target=process_image, daemon=True).start()

    def _update_ocr_display(self, ocr_text):
        """Update OCR display"""
        self.text_ocr.delete(1.0, tk.END)
        self.text_ocr.insert(tk.END, ocr_text)

    def fill_form_with_extracted_data(self, extracted):
        """Fill form fields with extracted data"""
        if not extracted:
            return
            
        def safe_insert(entry, value):
            entry.delete(0, tk.END)
            if value and str(value).strip():
                entry.insert(0, str(value).strip())
                # Highlight the field temporarily
                original_bg = entry.cget('bg')
                entry.config(bg='#E6FFE6')  # Light green
                self.root.after(2000, lambda: entry.config(bg=original_bg))
                return True
            return False
        
        # Fill all fields
        filled_count = 0
        fields_data = [
            (self.entry_product, extracted.get("product_name", "")),
            (self.entry_manu_name, extracted.get("manufacturer_name", "")),
            (self.entry_manu_addr, extracted.get("manufacturer_address", "")),
            (self.entry_manu_phone, extracted.get("manufacturer_phone", "")),
            (self.entry_imp_name, extracted.get("importer_name", "")),
            (self.entry_imp_addr, extracted.get("importer_address", "")),
            (self.entry_imp_phone, extracted.get("importer_phone", "")),
            (self.entry_mfg, extracted.get("manufacturing_date", "")),
            (self.entry_exp, extracted.get("expiry_date", "")),
            (self.entry_type, extracted.get("type", ""))
        ]
        
        for entry, value in fields_data:
            if safe_insert(entry, value):
                filled_count += 1
        
        # Update status
        if filled_count > 0:
            self.status_label.config(text=f"Filled {filled_count} fields", fg='green')
        else:
            self.status_label.config(text="No data extracted", fg='orange')
    
    def save_db_only(self):
        """Save data to database"""
        img_path = self.entry_image_path.get().strip()
        if not img_path or not os.path.exists(img_path):
           messagebox.showerror("Lỗi", "Vui lòng chọn file ảnh hợp lệ!")
           return

        # Validate required fields
        product_name = self.entry_product.get().strip()
        if not product_name:
           messagebox.showerror("Lỗi", "Vui lòng nhập đầy đủ tên sản phẩm!")
           return

        try:
            rec = {
              "image_name": os.path.basename(img_path),
              "image_path": img_path,
              "image_base64": encode_image_to_base64(img_path),
              "product_name": product_name,
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

            self.status_label.config(text="Saving to database...", fg='blue')
            ok, msg = save_to_db(rec)
            
            if ok:
               self.status_label.config(text="Saved successfully", fg='green')
               messagebox.showinfo("Thành Công", "Ảnh đã được lưu thành công vào database!")
               
               if messagebox.askyesno("Tiếp tục", "Bạn có muốn thêm ảnh khác không?"):
                   self.clear_form()
            else:
               self.status_label.config(text="Save failed", fg='red')
               messagebox.showerror("Lỗi", f"Lưu thất bại:\n\n{msg}")
        except Exception as e:
            self.status_label.config(text="Save error", fg='red')
            messagebox.showerror("Lỗi", f"Có lỗi khi lưu:\n\n{str(e)}")

    def export_json_only(self):
        """Export data to JSON file"""
        try:
            # Let user choose export location
            export_path = filedialog.asksaveasfilename(
                title="Chọn nơi lưu file JSON",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                initialfile=f"labels_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            
            if not export_path:
                return
                
            self.status_label.config(text="Exporting JSON...", fg='blue')
            ok, msg = export_json_from_db(export_path)
            
            if ok:
               self.status_label.config(text="Export completed", fg='green')
               messagebox.showinfo("Thành công", f"Đã xuất JSON thành công!\nFile: {export_path}")
               
               if messagebox.askyesno("Mở file", "Bạn có muốn mở thư mục chứa file không?"):
                   import subprocess
                   subprocess.run(['explorer', '/select,', export_path.replace('/', '\\')])
            else:
               self.status_label.config(text="Export failed", fg='red')
               messagebox.showerror("Lỗi", f"Xuất file thất bại:\n\n{msg}")
               
        except Exception as e:
            self.status_label.config(text="Export error", fg='red')
            messagebox.showerror("Lỗi", f"Có lỗi khi xuất:\n\n{str(e)}")


# ---------- Main Application ----------
def main():
    """Main application entry point"""
    try:
        # Check dependencies
        required_modules = ['PIL', 'mysql.connector', 'easyocr', 'ollama', 'cv2']
        missing_modules = []
        
        for module in required_modules:
            try:
                __import__(module)
            except ImportError:
                missing_modules.append(module)
        
        if missing_modules:
            print(f"Missing required modules: {', '.join(missing_modules)}")
            print("Please install them using:")
            print("pip install pillow mysql-connector-python easyocr ollama opencv-python")
            return
        
        # Test database connection
        try:
            conn = connect_db()
            conn.close()
            print("Database connection successful")
        except Exception as e:
            print(f"Database connection failed: {e}")
            print("Please check your MySQL configuration")
        
        # Test Ollama connection
        try:
            ollama.list()
            print("Ollama connection successful")
        except Exception as e:
            print(f"Ollama connection failed: {e}")
            print("Please ensure Ollama is running and llama3.1 model is available")
        
        # Start application
        root = tk.Tk()
        app = App(root)
        
        print("Application started successfully")
        print("Features available:")
        print("   - Simplified OCR processing")
        print("   - Enhanced Ollama AI extraction")
        print("   - Improved Vietnamese text support")
        print("   - Robust JSON parsing")
        print("   - Better error handling")
        
        root.mainloop()
        
    except Exception as e:
        print(f"Application startup failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()