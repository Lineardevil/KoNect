import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from supabase import create_client, Client
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional, List

load_dotenv()

app = FastAPI()

# 1. CẤU HÌNH CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. KẾT NỐI SUPABASE
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# 3. ĐƯỜNG DẪN THƯ MỤC (Sửa lại để chạy chuẩn trên Vercel)
# Dùng dirname của dirname để lùi lại 1 cấp từ Backend/ ra thư mục gốc
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "Frontend")

# Phục vụ file tĩnh - ĐẢM BẢO đường dẫn này tồn tại
app.mount(
    "/assets",
    StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")),
    name="assets",
)

# ============================================================
# PHẦN 1: TRẢ VỀ CÁC TRANG HTML (Đã sửa lỗi tên file)
# ============================================================

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/main")
async def read_main():
    # ĐÃ SỬA: từ "lỗi.html" thành "main.html"
    return FileResponse(os.path.join(FRONTEND_DIR, "main.html"))

@app.get("/create")
async def read_create():
    return FileResponse(os.path.join(FRONTEND_DIR, "create.html"))

@app.get("/chat")
async def read_chat():
    return FileResponse(os.path.join(FRONTEND_DIR, "chat.html"))

@app.get("/profile")
async def read_profile():
    return FileResponse(os.path.join(FRONTEND_DIR, "profile.html"))

@app.get("/reset-password")
async def read_reset():
    return FileResponse(os.path.join(FRONTEND_DIR, "reset-password.html"))

# ============================================================
# PHẦN 2: API NHÓM (/api/groups)
# ============================================================

# --- Định nghĩa dữ liệu khi tạo nhóm (khớp form trong create.html) ---
class GroupCreate(BaseModel):
    name: str
    description: str
    max_members: int
    privacy: str                       # "public" hoặc "private"
    tags: List[str]                    # Tối đa 5 tag
    cover_image: Optional[str] = None  # Ảnh bìa base64 (nếu có)
    created_by: Optional[str] = None   # User ID người tạo


# GET /api/groups — Lấy tất cả nhóm (đã có, giữ nguyên)
@app.get("/api/groups")
async def get_all_groups():
    response = supabase.table("groups").select("*").execute()
    return response.data


# GET /api/groups/search?keyword=...&tag=... — Tìm kiếm nhóm
@app.get("/api/groups/search")
async def search_groups(keyword: str = "", tag: str = ""):
    query = supabase.table("groups").select("*")
    if keyword:
        query = query.ilike("name", f"%{keyword}%")
    response = query.execute()
    results = response.data
    # Lọc theo tag nếu có (tags lưu dạng mảng trong Supabase)
    if tag and results:
        results = [g for g in results if tag in (g.get("tags") or [])]
    return results


# GET /api/groups/{group_id} — Lấy thông tin 1 nhóm cụ thể
@app.get("/api/groups/{group_id}")
async def get_group(group_id: str):
    response = supabase.table("groups").select("*").eq("id", group_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhóm")
    return response.data[0]


# POST /api/groups — Tạo nhóm mới (create.html gọi cái này)
@app.post("/api/groups")
async def create_group(group: GroupCreate):
    if not group.name or not group.description:
        raise HTTPException(status_code=400, detail="Thiếu tên hoặc mô tả nhóm")
    if group.max_members < 1 or group.max_members > 50:
        raise HTTPException(status_code=400, detail="Số thành viên phải từ 1 đến 50")
    if len(group.tags) > 5:
        raise HTTPException(status_code=400, detail="Tối đa 5 tag")
    if group.privacy not in ["public", "private"]:
        raise HTTPException(status_code=400, detail="Privacy phải là 'public' hoặc 'private'")

    new_group = {
        "name":        group.name,
        "description": group.description,
        "max_members": group.max_members,
        "privacy":     group.privacy,
        "tags":        group.tags,
        "cover_image": group.cover_image,
        "created_by":  group.created_by,
    }
    response = supabase.table("groups").insert(new_group).execute()
    return {"message": "Tạo nhóm thành công!", "data": response.data}


# DELETE /api/groups/{group_id} — Xóa nhóm
@app.delete("/api/groups/{group_id}")
async def delete_group(group_id: str):
    supabase.table("groups").delete().eq("id", group_id).execute()
    return {"message": "Đã xóa nhóm"}


# ============================================================
# PHẦN 3: API TIN NHẮN (/api/messages) — dùng cho chat.html
# ============================================================

# --- Định nghĩa dữ liệu khi gửi tin nhắn ---
class MessageSend(BaseModel):
    group_id: str
    sender_id: str
    sender_name: str
    content: str


# GET /api/messages/{group_id} — Lấy lịch sử chat của 1 nhóm
@app.get("/api/messages/{group_id}")
async def get_messages(group_id: str, limit: int = 50):
    response = (
        supabase.table("messages")
        .select("*")
        .eq("group_id", group_id)
        .order("created_at", desc=False)  # Cũ nhất lên trên
        .limit(limit)
        .execute()
    )
    return response.data


# POST /api/messages — Gửi tin nhắn mới
@app.post("/api/messages")
async def send_message(msg: MessageSend):
    if not msg.content.strip():
        raise HTTPException(status_code=400, detail="Tin nhắn không được trống")
    new_message = {
        "group_id":    msg.group_id,
        "sender_id":   msg.sender_id,
        "sender_name": msg.sender_name,
        "content":     msg.content.strip(),
    }
    response = supabase.table("messages").insert(new_message).execute()
    return {"message": "Gửi thành công", "data": response.data}


# ============================================================
# PHẦN 4: API THÀNH VIÊN NHÓM (/api/groups/{id}/members)
# ============================================================

# GET /api/groups/{group_id}/members — Xem danh sách thành viên
@app.get("/api/groups/{group_id}/members")
async def get_members(group_id: str):
    response = (
        supabase.table("group_members")
        .select("*")
        .eq("group_id", group_id)
        .execute()
    )
    return response.data


# POST /api/groups/{group_id}/join — Tham gia nhóm
@app.post("/api/groups/{group_id}/join")
async def join_group(group_id: str, user_id: str):
    # Kiểm tra nhóm tồn tại
    group_res = supabase.table("groups").select("*").eq("id", group_id).execute()
    if not group_res.data:
        raise HTTPException(status_code=404, detail="Nhóm không tồn tại")

    # Kiểm tra đã là thành viên chưa
    existing = (
        supabase.table("group_members")
        .select("*")
        .eq("group_id", group_id)
        .eq("user_id", user_id)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=400, detail="Bạn đã là thành viên nhóm này rồi")

    supabase.table("group_members").insert({
        "group_id": group_id,
        "user_id":  user_id,
    }).execute()
    return {"message": "Tham gia nhóm thành công!"}


# POST /api/groups/{group_id}/leave—Rời nhóm
@app.post("/api/groups/{group_id}/leave")
async def leave_group(group_id: str, user_id: str):
    supabase.table("group_members").delete() \
        .eq("group_id", group_id) \
        .eq("user_id", user_id) \
        .execute()
    return {"message": "Đã rời nhóm"}
