import os
from fastapi import FastAPI
from supabase import create_client, Client
from dotenv import load_dotenv
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()
app = FastAPI()

# 1. Cấu hình CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Kết nối Supabase
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# Xác định đường dẫn thư mục frontend (Lùi ra 1 cấp từ backend)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

# --- PHẦN 1: PHỤC VỤ CÁC TRANG GIAO DIỆN (HTML) ---

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/main")
async def read_main():
    return FileResponse(os.path.join(FRONTEND_DIR, "main.html"))

@app.get("/reset-password")
async def read_reset():
    return FileResponse(os.path.join(FRONTEND_DIR, "reset-password.html"))

@app.get("/profile")
async def read_profile():
    return FileResponse(os.path.join(FRONTEND_DIR, "profile.html"))

# --- PHẦN 2: API DỮ LIỆU ---

@app.get("/api/groups")
async def get_all_groups():
    # Lấy dữ liệu nhóm để đổ vào Trang 2
    response = supabase.table("groups").select("*").execute()
    return response.data